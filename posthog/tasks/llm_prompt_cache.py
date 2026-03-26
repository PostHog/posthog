import logging

from celery import shared_task

from posthog.storage.llm_prompt_cache import invalidate_prompt_version_cache_range
from posthog.tasks.utils import CeleryQueue

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def invalidate_archived_prompt_versions_cache_task(
    team_id: int, prompt_name: str, start_version: int, end_version: int
) -> None:
    try:
        invalidate_prompt_version_cache_range(team_id, prompt_name, start_version, end_version)
    except Exception:
        logger.exception(
            "Failed to invalidate archived prompt version cache range",
            extra={
                "team_id": team_id,
                "prompt_name": prompt_name,
                "start_version": start_version,
                "end_version": end_version,
            },
        )
        raise
