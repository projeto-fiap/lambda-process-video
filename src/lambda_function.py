import os
import shutil
import boto3
import zipfile
import subprocess
from typing import Dict

s3 = boto3.client("s3")
BUCKET_NAME = "bucket-video-hackaton"
VIDEO_FOLDER = "videos/"
OUTPUT_FOLDER = "output/"
VALID_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"}

def is_valid_video_file(file_name: str) -> bool:
    return os.path.splitext(file_name)[1].lower() in VALID_VIDEO_EXTENSIONS

def download_video_from_s3(video_name: str, local_video: str) -> None:
    video_path = f"{VIDEO_FOLDER}{video_name}"
    s3.download_file(BUCKET_NAME, video_path, local_video)

def extract_frames(video_path: str, output_folder: str, fps: int = 1, resolution: str = "1920:1080") -> None:
    os.makedirs(output_folder, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    subprocess.run([ 
        "ffmpeg", "-i", video_path, "-vf", f"fps={fps},scale={resolution}", "-q:v", "2", 
        f"{output_folder}/{base_name}_%04d.jpg"
    ], check=True)

def create_zip_file(source_folder: str, zip_path: str) -> None:
    with zipfile.ZipFile(zip_path, "w") as zipf:
        for file in os.listdir(source_folder):
            zipf.write(os.path.join(source_folder, file), file)

def upload_to_s3(file_path: str, s3_path: str) -> None:
    s3.upload_file(file_path, BUCKET_NAME, s3_path, ExtraArgs={"ACL": "public-read"})

def delete_video_from_s3(video_name: str) -> None:
    video_path = f"{VIDEO_FOLDER}{video_name}"
    s3.delete_object(Bucket=BUCKET_NAME, Key=video_path)

def generate_presigned_url(s3_path: str, expiration: int = 3600) -> str:
    """Gera uma URL assinada para download de um arquivo S3."""
    url = s3.generate_presigned_url('get_object',
                                    Params={'Bucket': BUCKET_NAME, 'Key': s3_path},
                                    ExpiresIn=expiration)
    return url

def lambda_handler(event: Dict, context) -> Dict:
    video_name = event.get("filename")
    delete_video = event.get("delete_video", True)
    
    if not is_valid_video_file(video_name):
        return {"error": "Arquivo enviado não é um vídeo válido."}

    base_name, _ = os.path.splitext(video_name)
    
    # Pasta exclusiva para esse vídeo
    working_dir = f"/tmp/{base_name}"
    os.makedirs(working_dir, exist_ok=True)

    local_video = os.path.join(working_dir, video_name)
    frames_folder = os.path.join(working_dir, "frames")
    zip_path = os.path.join(working_dir, f"{base_name}.zip")
    output_aws = f"{OUTPUT_FOLDER}{base_name}.zip"

    try:
        download_video_from_s3(video_name, local_video)
        extract_frames(local_video, frames_folder)
        create_zip_file(frames_folder, zip_path)
        upload_to_s3(zip_path, output_aws)

        # Gera a URL assinada para o arquivo zip
        presigned_url = generate_presigned_url(output_aws)

        if delete_video:
            delete_video_from_s3(video_name)

        return {
            "message": f"Frames zipados enviados para s3://{BUCKET_NAME}/{output_aws}",
            "storage": f"s3://{BUCKET_NAME}/{output_aws}",
            "download_url": f"https://{BUCKET_NAME}.s3.amazonaws.com/{output_aws}",
            "presigned_url": presigned_url,
            "video_deleted": f"s3://{BUCKET_NAME}/{VIDEO_FOLDER}{video_name}" if delete_video else "Não apagado"
        }
    finally:
        # Limpa tudo referente ao vídeo
        if os.path.exists(working_dir):
            shutil.rmtree(working_dir)
