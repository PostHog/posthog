import uuid

from celery import shared_task
from structlog import get_logger

from posthog.tasks.utils import CeleryQueue

logger = get_logger(__name__)

REVERSE_PROXY_KIND = "reverse_proxy"

# A proxy that just went live has no proxied events behind it yet, and the check only passes once
# it sees one. Re-check immediately for the users who were already sending traffic, then again as
# the first proxied events land, rather than leaving the warning up until tomorrow's scheduled run.
REVERSE_PROXY_RECHECK_DELAYS_SECONDS = (0, 15 * 60, 60 * 60)


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


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def recheck_reverse_proxy_for_organization(organization_id: str) -> None:
    from posthog.models.team import Team

    team_ids = list(Team.objects.filter(organization_id=organization_id).values_list("id", flat=True))
    logger.info(
        "recheck_reverse_proxy_for_organization.starting", organization_id=organization_id, team_count=len(team_ids)
    )
    for team_id in team_ids:
        evaluate_health_check_for_team(kind=REVERSE_PROXY_KIND, team_id=team_id)


def schedule_reverse_proxy_recheck(organization_id: uuid.UUID | str) -> None:
    """Re-run the reverse proxy check for an organization whose proxy just went live.

    Best effort: the proxy is already provisioned by the time this runs, so a broker problem here
    must never fail the provisioning workflow. The worst case is the warning staying up until the
    next scheduled run, which is what happens today anyway.
    """
    for delay_seconds in REVERSE_PROXY_RECHECK_DELAYS_SECONDS:
        try:
            recheck_reverse_proxy_for_organization.apply_async(args=[str(organization_id)], countdown=delay_seconds)
        except Exception:
            logger.warning(
                "schedule_reverse_proxy_recheck.failed",
                organization_id=str(organization_id),
                delay_seconds=delay_seconds,
                exc_info=True,
            )
