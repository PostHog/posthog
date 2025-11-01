from datetime import datetime
import os
import structlog
from google.genai import Client
from google.genai.errors import APIError
from google.genai.types import (
    Blob,
    Content,
    File,
    FileData,
    GenerateContentConfig,
    MediaResolution,
    Part,
    VideoMetadata,
)


logger = structlog.get_logger(__name__)

# Recording (35 minutes): https://us.posthog.com/project/2/replay/0199e6a9-2a17-7209-bcb8-ad1001225d04
# Recording (2 hours 37 minutes): https://us.posthog.com/project/2/replay/0199e6a1-a8ce-7466-9243-3aaf52af0d9a


def get_file(client: Client, file_name: str) -> File | None:
    file = client.files.get(name=file_name)
    if not file:
        logger.error(f"File {file_name} not found")
        return None
    return file


def upload_video_to_gemini(client: Client, video_path: str) -> File:
    uploaded_file = client.files.upload(file=video_path)
    if not uploaded_file:
        raise ValueError("Failed to upload video to Gemini")
    if not uploaded_file.name:
        raise ValueError("Failed to get name of uploaded video")
    return uploaded_file


BASE_PROMPT = """
- Describe what's happening in the video as a a list of salient moments.
- It's a recording of the part of a web analytics session of a user.
- Red lines indicate mouse movements, and should be ignored.
- Output in the `*   **MM:SS - MM:SS:** <description>` format.
"""

if __name__ == "__main__":
    model_id = "gemini-2.5-flash-preview-09-2025"
    media_resolution = MediaResolution.MEDIA_RESOLUTION_MEDIUM
    # Testing on the video of the chart reload
    # flash lite shows +- the same results at low and at medium
    # flash at low shows also the same results, but flash at medium actually understands what happening (chart recalculation)
    # sticking to flash at medium for the MVP

    # Ensure the file is uploaded
    input_video_path = (
        "/Users/woutut/Desktop/test_videos/replay-0199e6a9-2a17-7209-bcb8-ad1001225d04-2025-11-01-16-50.mp4"
    )
    expected_file_name = "files/1cygz2sk56fn"
    base_client = Client(api_key=os.getenv("GEMINI_API_KEY"))
    uploaded_video = get_file(base_client, expected_file_name)
    if not uploaded_video:
        uploaded_video = upload_video_to_gemini(base_client, input_video_path)
        logger.info(f"Uploaded video to Gemini: {uploaded_video.name}")
    # Analyze the video
    logger.info(f"Analyzing video with model: {model_id}")
    response = base_client.models.generate_content(
        model=model_id,
        contents=Content(
            parts=[
                Part(
                    file_data=FileData(file_uri=uploaded_video.uri, mime_type=uploaded_video.mime_type),
                    video_metadata=VideoMetadata(start_offset="1182s", end_offset="1197s"),
                ),
                Part(text=BASE_PROMPT),
            ]
        ),
        config=GenerateContentConfig(
            media_resolution=media_resolution,
        ),
    )
    print(response.text)
    timestamp = datetime.now().isoformat()
    with open(f"transcript_{model_id}_{media_resolution.name}_{timestamp}.txt", "w") as f:
        f.write(response.text)
