import structlog
from celery import shared_task

from posthog.models import Insight
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value, max_retries=1)
def extract_insight_query_metadata(insight_id: str) -> None:
    insight = Insight.objects.get(pk=insight_id)
    insight.generate_query_metadata()
    insight.save()
