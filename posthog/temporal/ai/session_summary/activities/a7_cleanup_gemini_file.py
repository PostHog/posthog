"""
Activity 7 of the video-based summarization workflow:
Delete the uploaded video file from Gemini to free storage quota.
"""

from django.conf import settings

import structlog
import temporalio
from asgiref.sync import sync_to_async
from google.genai import Client as RawGenAIClient

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def cleanup_gemini_file_activity(gemini_file_name: str, session_id: str) -> None:
    """Delete an uploaded file from Gemini. Best-effort: logs failures but never raises."""
    try:
        raw_client = RawGenAIClient(api_key=settings.GEMINI_API_KEY)
        await sync_to_async(raw_client.files.delete, thread_sensitive=False)(name=gemini_file_name)
        logger.info(
            f"Deleted Gemini file {gemini_file_name} for session {session_id}",
            gemini_file_name=gemini_file_name,
            session_id=session_id,
            signals_type="session-summaries",
        )
    except Exception:
        logger.exception(
            f"Failed to delete Gemini file {gemini_file_name} for session {session_id}",
            gemini_file_name=gemini_file_name,
            session_id=session_id,
            signals_type="session-summaries",
        )
