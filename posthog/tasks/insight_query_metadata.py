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
    reject_on_worker_lost=True,
    track_started=True,
    default_retry_delay=10 * 60,  # 10 minutes
)
def extract_insight_query_metadata(insight_id: int) -> None:
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


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    expires=60 * 60,
    track_started=True,
)
def fill_insights_missing_query_metadata() -> None:
    from django.db.models import Q, F

    insights = Insight.objects_including_soft_deleted.filter(
        # Insights with no metadata or empty metadata
        (Q(query_metadata__isnull=True) | Q(query_metadata={}))
        |
        # Insights with outdated metadata
        (
            Q(query_metadata__isnull=False)
            & Q(query_metadata__has_key="updated_at")
            & Q(last_modified_at__gt=F("query_metadata__updated_at"))
        )
    ).only("id")

    for insight in insights.iterator(chunk_size=100):
        extract_insight_query_metadata.delay(insight_id=insight.id)

    logger.info(
        "Scheduled task to fill missing query metadata for insights",
        total_insights=insights.count(),
    )
