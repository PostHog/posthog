from django.conf import settings

import structlog
from celery import shared_task

from posthog.models.integration import (
    FirebaseIntegration,
    GitHubIntegration,
    GoogleCloudIntegration,
    defer_repository_cache_fields,
)
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.INTEGRATIONS.value)
@skip_team_scope_audit
def refresh_integrations() -> int:
    from posthog.models.integration import Integration, OauthIntegration

    oauth_integrations = defer_repository_cache_fields(
        Integration.objects.filter(kind__in=OauthIntegration.supported_kinds).exclude(kind="meta-ads").all()
    )

    for integration in oauth_integrations:
        oauth_integration = OauthIntegration(integration)

        if oauth_integration.access_token_expired():
            refresh_integration.delay(integration.id)

    gcloud_integrations = defer_repository_cache_fields(
        Integration.objects.filter(kind__in=GoogleCloudIntegration.supported_kinds).all()
    )

    for integration in gcloud_integrations:
        gcloud_integration = GoogleCloudIntegration(integration)

        if gcloud_integration.access_token_expired():
            refresh_integration.delay(integration.id)

    github_integrations = defer_repository_cache_fields(Integration.objects.filter(kind="github").all())

    for integration in github_integrations:
        github_integration = GitHubIntegration(integration)

        if github_integration.access_token_expired():
            refresh_integration.delay(integration.id)

    firebase_integrations = defer_repository_cache_fields(Integration.objects.filter(kind="firebase").all())

    for integration in firebase_integrations:
        firebase_integration = FirebaseIntegration(integration)

        if firebase_integration.access_token_expired():
            refresh_integration.delay(integration.id)

    return 0


@shared_task(ignore_result=True, queue=CeleryQueue.INTEGRATIONS.value)
@skip_team_scope_audit
def refresh_integration(id: int) -> int:
    from posthog.models.integration import Integration, OauthIntegration

    integration = defer_repository_cache_fields(Integration.objects.all()).get(id=id)

    if integration.kind in OauthIntegration.supported_kinds:
        oauth_integration = OauthIntegration(integration)
        oauth_integration.refresh_access_token()
    elif integration.kind in GoogleCloudIntegration.supported_kinds:
        gcloud_integration = GoogleCloudIntegration(integration)
        gcloud_integration.refresh_access_token()
    elif integration.kind == "github":
        github_integration = GitHubIntegration(integration)
        github_integration.refresh_access_token()
    elif integration.kind == "firebase":
        firebase_integration = FirebaseIntegration(integration)
        firebase_integration.refresh_access_token()

    return 0


@shared_task(ignore_result=True, queue=CeleryQueue.INTEGRATIONS.value)
@skip_team_scope_audit
def push_vercel_secrets(team_id: int) -> None:
    from posthog.models.team import Team

    from ee.vercel.integration import VercelIntegration

    team = Team.objects.get(id=team_id)
    VercelIntegration.push_secrets_to_vercel(team)


@shared_task(ignore_result=True, queue=CeleryQueue.INTEGRATIONS.value)
@skip_team_scope_audit
def proxy_github_webhook_to_hognipotent(body: bytes, headers: dict[str, str]) -> None:
    # Runs out-of-band so a slow or unreachable hognipotent never eats GitHub's
    # 10-second delivery budget and forces retries.
    if not settings.HOGNIPOTENT_WEBHOOK_URL:
        return

    import requests

    try:
        requests.post(settings.HOGNIPOTENT_WEBHOOK_URL, data=body, headers=headers, timeout=10)
    except Exception as e:
        logger.warning("hognipotent_webhook_proxy_failed", error=str(e))
