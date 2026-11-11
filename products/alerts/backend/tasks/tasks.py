from celery import shared_task

from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.alerts_platform.backend.facade.api import remove_subscriber


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    max_retries=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
# Cross-team on purpose: it covers every team of one organization, and each destination write is scoped to its team.
@skip_team_scope_audit
def remove_departed_subscriber(organization_id: str, user_id: int) -> None:
    """Takes a user who left an organization out of every subscriber destination of its alerts.

    A retry repeats the whole scan, which is safe because it only removes the user. A user who
    joined again before the task ran is left alone, because their destinations may be new.
    """
    if OrganizationMembership.objects.filter(organization_id=organization_id, user_id=user_id).exists():
        return
    team_ids = list(Team.objects.filter(organization_id=organization_id).values_list("id", flat=True))
    remove_subscriber(team_ids=team_ids, user_id=user_id)
