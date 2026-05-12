from celery import shared_task
from structlog import get_logger

from posthog.tasks.utils import CeleryQueue

logger = get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def evaluate_health_check_for_team(kind: str, team_id: int) -> None:
    # Run a single health check synchronously for one team and reconcile its active issues.
    # Triggered by signals on the underlying data so users see fresh state before the next
    # scheduled batch run; safe to be called multiple times — the reconciliation is idempotent.
    #
    # Imports are deferred: posthog.temporal.health_checks.__init__ pulls in posthog.dags,
    # which calls django.setup() at import time and re-enters Django's app population if
    # this module is loaded during Django boot (which happens via posthog.tasks autoload).
    from posthog.temporal.health_checks.processing import _process_batch_detection
    from posthog.temporal.health_checks.registry import ensure_registry_loaded, get_detect_fn

    ensure_registry_loaded()
    try:
        detect_fn = get_detect_fn(kind)
    except KeyError:
        logger.warning("evaluate_health_check_for_team.unknown_kind", kind=kind, team_id=team_id)
        return

    _process_batch_detection(team_ids=[team_id], kind=kind, detect_fn=detect_fn)
