from django.conf import settings

import structlog
import temporalio
from asgiref.sync import sync_to_async
from google.genai import Client as RawGenAIClient

from posthog.temporal.session_replay.gemini_cleanup_sweep.tracking import untrack_uploaded_file

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def cleanup_gemini_file_activity(gemini_file_name: str, session_id: str) -> None:
    """Best-effort: on any failure the tracking key is left for the sweep to retry."""
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
        return

    await untrack_uploaded_file(gemini_file_name)
