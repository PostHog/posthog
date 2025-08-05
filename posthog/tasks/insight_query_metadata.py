import structlog
from celery import shared_task
from django.db import transaction

from posthog.models import Insight
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value, max_retries=1)
def extract_insight_query_metadata(insight_id: str) -> None:
    try:
        with transaction.atomic():
            insight = (
                Insight.objects.select_for_update(of=("self",))
                .select_related("team")
                .only("query", "query_metadata", "team")
                .get(pk=insight_id)
            )
            insight.generate_query_metadata()
            insight.save(update_fields=["query_metadata"])
    except Insight.DoesNotExist as e:
        logger.exception(
            "Failed to extract query metadata - insight does not exist", insight_id=insight_id, error=str(e)
        )
        # Don't retry for non-existent insights
        return
    except Exception as e:
        logger.exception("Failed to extract query metadata for insight", insight_id=insight_id, error=str(e))
        raise
