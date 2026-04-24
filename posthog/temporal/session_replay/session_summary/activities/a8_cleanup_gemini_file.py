"""
Activity 8 of the video-based summarization workflow:
Delete the uploaded video file from Gemini to free storage quota.
"""

from django.conf import settings

import structlog
import temporalio
from asgiref.sync import sync_to_async
from google.genai import Client as RawGenAIClient

logger = structlog.get_logger(__name__)


def _is_not_found_error(exc: BaseException) -> bool:
    """Best-effort check for a 404 / 'not found' error from the Gemini files API.

    The google-genai SDK raises ``google.genai.errors.ClientError`` with a ``code`` of 404
    when the file does not exist. We also match on message text as a fallback in case the
    SDK changes its error surface.
    """
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code == 404:
        return True
    msg = str(exc).lower()
    return "not found" in msg or "404" in msg


@temporalio.activity.defn
async def cleanup_gemini_file_activity(gemini_file_name: str, session_id: str) -> None:
    """Delete an uploaded file from Gemini.

    Raises on unexpected failures so Temporal retries the activity — the workflow's
    ``RetryPolicy`` controls total attempts. A 404 (file already gone, e.g. because a
    prior attempt succeeded but the worker crashed before acknowledging it) is treated
    as success so retries don't propagate a spurious error once the post-condition is
    already satisfied.
    """
    raw_client = RawGenAIClient(api_key=settings.GEMINI_API_KEY)
    try:
        await sync_to_async(raw_client.files.delete, thread_sensitive=False)(name=gemini_file_name)
    except Exception as e:
        if _is_not_found_error(e):
            logger.info(
                f"Gemini file {gemini_file_name} already gone for session {session_id} — treating as cleaned up",
                gemini_file_name=gemini_file_name,
                session_id=session_id,
                signals_type="session-summaries",
            )
            return
        logger.exception(
            f"Failed to delete Gemini file {gemini_file_name} for session {session_id} — will be retried",
            gemini_file_name=gemini_file_name,
            session_id=session_id,
            signals_type="session-summaries",
        )
        raise
    logger.info(
        f"Deleted Gemini file {gemini_file_name} for session {session_id}",
        gemini_file_name=gemini_file_name,
        session_id=session_id,
        signals_type="session-summaries",
    )
