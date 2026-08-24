"""Celery task that counts Stripe marketplace credentials on the orchestrator OAuth application.

A marketplace token is readable by every member of the customer's Stripe account. The
orchestrator application can issue deep links, which exchange for a full Django session. A
marketplace token minted on the orchestrator application therefore hands session takeover to
anyone in that Stripe account. The two applications were split so that cannot happen, and the
credentials issued before the split were rotated off on 2026-08-24.

Nothing fails loudly if a code path starts minting on the orchestrator again. The tokens work,
the customer sees no error, and the exposure is silent. This task makes that state observable.
"""

from django.conf import settings
from django.utils import timezone

import structlog
from celery import shared_task
from prometheus_client import Gauge

from posthog.exceptions_capture import capture_exception
from posthog.tasks.utils import CeleryQueue, PushGatewayTask

logger = structlog.get_logger(__name__)


class MarketplaceTokensOnOrchestratorApp(Exception):
    """Raised for error tracking only, so the finding reaches a human even without the metric."""


@shared_task(
    bind=True,
    base=PushGatewayTask,
    ignore_result=True,
    queue=CeleryQueue.INTEGRATIONS.value,
    soft_time_limit=5 * 60,
    time_limit=6 * 60,
)
def audit_stripe_marketplace_tokens_task(self: PushGatewayTask) -> None:
    """Count live single-team credentials on the orchestrator application for Stripe-integrated teams.

    Metric: posthog_stripe_marketplace_tokens_on_orchestrator_app

    The predicate matches the one `rotate_stripe_marketplace_tokens` evicts on, which measured
    zero in prod-us and prod-eu after the 2026-08-24 rotation. Any non-zero value means either a
    marketplace token was minted on the orchestrator application, or a single-team provisioning
    token now exists for a team that also has a Stripe integration. Both need a human to look.

    Single-team is the discriminator because provisioning tokens are widened across every team
    the partner provisioned, while a marketplace token is always scoped to the one team its
    Stripe account is linked to.
    """
    from posthog.models.integration import Integration
    from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken

    orchestrator_client_id = settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID
    if not orchestrator_client_id:
        logger.info("STRIPE_POSTHOG_OAUTH_CLIENT_ID not set, skipping stripe marketplace token audit")
        return

    orchestrator = OAuthApplication.objects.filter(client_id=orchestrator_client_id).first()
    if orchestrator is None:
        logger.info("No OAuthApplication for STRIPE_POSTHOG_OAUTH_CLIENT_ID, skipping stripe marketplace token audit")
        return

    stripe_team_ids = set(Integration.objects.filter(kind="stripe").values_list("team_id", flat=True))
    if not stripe_team_ids:
        _publish(self, 0)
        return

    now = timezone.now()
    # Filter to single-team credentials in Postgres first. That set is small on the orchestrator
    # application, so the team-membership intersection is cheap to finish in Python and avoids
    # sending a thousand-element array into the query.
    offending_teams: set[int] = set()
    credentials = 0

    for scoped_teams in OAuthAccessToken.objects.filter(
        application=orchestrator, expires__gt=now, scoped_teams__len=1
    ).values_list("scoped_teams", flat=True):
        if scoped_teams[0] in stripe_team_ids:
            offending_teams.add(scoped_teams[0])
            credentials += 1

    for scoped_teams in OAuthRefreshToken.objects.filter(
        application=orchestrator, revoked__isnull=True, scoped_teams__len=1
    ).values_list("scoped_teams", flat=True):
        if scoped_teams[0] in stripe_team_ids:
            offending_teams.add(scoped_teams[0])
            credentials += 1

    if credentials:
        logger.error(
            "Stripe marketplace credentials found on the orchestrator OAuth application",
            credentials=credentials,
            teams=sorted(offending_teams)[:20],
            team_count=len(offending_teams),
        )
        capture_exception(
            MarketplaceTokensOnOrchestratorApp(
                f"{credentials} live credentials across {len(offending_teams)} teams sit on the "
                "orchestrator OAuth application, which can issue deep links"
            ),
            {"team_count": len(offending_teams), "teams": sorted(offending_teams)[:20]},
        )

    _publish(self, credentials)


def _publish(task: PushGatewayTask, credentials: int) -> None:
    if task.metrics_registry is None:
        return
    Gauge(
        "posthog_stripe_marketplace_tokens_on_orchestrator_app",
        "Live single-team OAuth credentials on the Stripe orchestrator application for teams "
        "with a Stripe integration. Steady state is 0; any other value is a session-takeover exposure.",
        registry=task.metrics_registry,
    ).set(credentials)
