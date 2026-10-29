from datetime import datetime

import structlog
from celery import Task, shared_task

from posthog.tasks.utils import CeleryQueue

from products.ai_training.backend.config import privacy_enabled
from products.ai_training.backend.logic.deletion import resolve_person_training_sessions
from products.ai_training.backend.privacy.store import AITrainingPrivacyStore

logger = structlog.get_logger(__name__)


@shared_task(
    name="posthog.tasks.ai_training_privacy.process_ai_training_privacy_requests",
    ignore_result=True,
    queue=CeleryQueue.AI_RESEARCH_PRIVACY.value,
    soft_time_limit=270,
    time_limit=300,
)
def process_ai_training_privacy_requests() -> None:
    if privacy_enabled():
        AITrainingPrivacyStore.from_settings().drain()


# The retries span about 24 hours, well inside the 10 days that deleted recordings keep their
# replay index rows. Each wait stays under the Redis broker's one-hour visibility timeout,
# because a longer wait makes the broker deliver the waiting retry a second time.
PERSON_LOOKUP_MAX_RETRIES = 52
PERSON_LOOKUP_RETRY_BASE_SECONDS = 60
PERSON_LOOKUP_RETRY_MAX_SECONDS = 1800


def person_lookup_retry_countdown(retries: int) -> int:
    return min(PERSON_LOOKUP_RETRY_BASE_SECONDS * 2**retries, PERSON_LOOKUP_RETRY_MAX_SECONDS)


# Late ack plus reject-on-worker-lost redeliver the lookup when a worker restarts mid-run. The
# caller has deleted the person by then, so this task holds the only copy of its distinct IDs.
@shared_task(
    bind=True,
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=PERSON_LOOKUP_MAX_RETRIES,
)
def resolve_person_training_sessions_task(
    self: Task, team_id: int, distinct_ids: list[str], started_before: str
) -> None:
    try:
        resolve_person_training_sessions(team_id, distinct_ids, datetime.fromisoformat(started_before))
    except Exception as exc:
        retries = self.request.retries
        if retries >= PERSON_LOOKUP_MAX_RETRIES:
            logger.exception(
                "ai_training.person_lookup_gave_up",
                team_id=team_id,
                distinct_id_count=len(distinct_ids),
                retries=retries,
                error_type=type(exc).__name__,
            )
        # Past max_retries this raises ``exc`` instead of scheduling another run.
        raise self.retry(exc=exc, countdown=person_lookup_retry_countdown(retries))
