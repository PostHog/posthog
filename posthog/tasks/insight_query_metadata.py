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


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value, expires=60 * 60)
def fill_insights_missing_query_metadata() -> None:
    from datetime import timedelta
    from django.db.models import Q
    from django.db.models.functions import Now

    one_day_ago = Now() - timedelta(days=1)

    insights = Insight.objects_including_soft_deleted.filter(
        (Q(query_metadata__isnull=True) | Q(query_metadata={}))
        & (Q(created_at__gte=one_day_ago) | Q(last_modified_at__gte=one_day_ago))
    ).only("id")

    for insight in insights.iterator(chunk_size=100):
        extract_insight_query_metadata.delay(insight_id=insight.id)
