from django.conf import settings

import temporalio.activity
from asgiref.sync import sync_to_async
from google.genai import Client as RawGenAIClient

from posthog.temporal.ai.session_summary.types.video import UploadedVideo


@temporalio.activity.defn
async def delete_uploaded_video_from_gemini_activity(uploaded_video: UploadedVideo) -> None:
    """Delete the uploaded video from Gemini. That's it."""
    if not uploaded_video.file_name:
        raise ValueError("Uploaded video cannot be deleted as it has no file name")
    raw_client = RawGenAIClient(api_key=settings.GEMINI_API_KEY)
    await sync_to_async(raw_client.files.delete, thread_sensitive=False)(name=uploaded_video.file_name)
