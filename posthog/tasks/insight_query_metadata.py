import structlog
from celery import shared_task
from django.db import transaction

from posthog.models import Insight
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    max_retries=1,
    acks_late=True,
    reject_on_worker_lost=True,
    track_started=True,
    default_retry_delay=10 * 60,  # 10 minutes
)
def extract_insight_query_metadata(insight_id: str) -> None:
    try:
        logger.warn(
            "Extracting query metadata for insight",
            insight_id=insight_id,
        )
        with transaction.atomic():
            insight = (
                Insight.objects_including_soft_deleted.select_for_update(of=("self",))
                .select_related("team")
                .only("query", "query_metadata", "team")
                .get(pk=insight_id)
            )
            insight.generate_query_metadata()
            insight.save(update_fields=["query_metadata"])
    except Exception as e:
        logger.exception("Failed to extract query metadata for insight", insight_id=insight_id, error=str(e))
        raise
