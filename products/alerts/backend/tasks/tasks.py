from uuid import UUID

import structlog
from celery import shared_task

from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_alert_wording import insight_alert_url
from products.alerts_platform.backend.facade.api import remove_subscriber
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.delivery import send_delivery_test

logger = structlog.get_logger(__name__)

# Each destination's own HTTP timeouts bound one send, and a receiver that keeps answering slowly
# could still hold the task. This bounds the whole test.
DELIVERY_TEST_SOFT_TIME_LIMIT_SECONDS = 60
DELIVERY_TEST_TIME_LIMIT_SECONDS = 90


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


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    soft_time_limit=DELIVERY_TEST_SOFT_TIME_LIMIT_SECONDS,
    time_limit=DELIVERY_TEST_TIME_LIMIT_SECONDS,
)
def send_insight_alert_delivery_test(team_id: int, alert_id: str, alert_name: str, insight_short_id: str) -> None:
    """Sends the test message to an insight alert's destination rows, off the request, so a slow
    receiver cannot hold an API worker. A test is not retried: the person can send another."""
    with team_scope(team_id):
        outcome = send_delivery_test(
            team_id=team_id,
            public_id=UUID(alert_id),
            source=SourceKind.INSIGHT,
            alert_name=alert_name,
            source_alert_url=insight_alert_url(team_id, insight_short_id, alert_id),
        )
    if outcome.failed:
        logger.info("insight_alert_delivery_test_failed", team_id=team_id, alert_id=alert_id, failed=outcome.failed)
