from celery import shared_task

from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.api import remove_subscriber


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    max_retries=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
# Cross-team on purpose: it covers every team of one organization, and each write is scoped to its alert's team.
@skip_team_scope_audit
def remove_departed_subscriber(organization_id: str, user_id: int, alert_ids: list[str] | None = None) -> None:
    """Brings the subscriber destinations of an organization's alerts in line after a user left it.

    An alert with an insight row is rewritten from its subscriptions, so it matches them whether or
    not the user has joined again since. An alert with no insight row has only its destinations, so
    the user is taken out of those only while they are still not a member. A retry repeats both
    steps, which leaves the same result.
    """
    from products.alerts.backend.platform_subscribers import sync_subscriber_destinations  # noqa: PLC0415 - cycle

    for alert in AlertConfiguration.objects.select_related("insight").filter(id__in=alert_ids or []):
        sync_subscriber_destinations(alert)
    if OrganizationMembership.objects.filter(organization_id=organization_id, user_id=user_id).exists():
        return
    team_ids = list(Team.objects.filter(organization_id=organization_id).values_list("id", flat=True))
    remove_subscriber(team_ids=team_ids, user_id=user_id)
