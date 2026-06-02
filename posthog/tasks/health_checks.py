from celery import shared_task
from structlog import get_logger

from posthog.tasks.utils import CeleryQueue

logger = get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def evaluate_health_check_for_team(kind: str, team_id: int) -> None:
    # Deferred: posthog.dags.__init__ calls django.setup() and would re-enter if loaded during boot.
    from posthog.temporal.health_checks.processing import _process_batch_detection
    from posthog.temporal.health_checks.registry import ensure_registry_loaded, get_detect_fn

    ensure_registry_loaded()
    try:
        detect_fn = get_detect_fn(kind)
    except KeyError:
        logger.warning("evaluate_health_check_for_team.unknown_kind", kind=kind, team_id=team_id)
        return

    _process_batch_detection(team_ids=[team_id], kind=kind, detect_fn=detect_fn)
