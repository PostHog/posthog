from celery import shared_task

from posthog.models.integration import (
    FirebaseIntegration,
    GitHubIntegration,
    GoogleCloudIntegration,
    defer_repository_cache_fields,
)
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.providers import SESProvider


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

    # Re-check freshness against the just-loaded row before minting. Under an INTEGRATIONS queue
    # backlog several duplicate refreshes can pile up for the same row; the first mints a fresh token
    # and this keeps the rest from re-minting one that's already valid.
    if integration.kind in OauthIntegration.supported_kinds:
        oauth_integration = OauthIntegration(integration)
        if oauth_integration.access_token_expired():
            oauth_integration.refresh_access_token()
    elif integration.kind in GoogleCloudIntegration.supported_kinds:
        gcloud_integration = GoogleCloudIntegration(integration)
        if gcloud_integration.access_token_expired():
            gcloud_integration.refresh_access_token()
    elif integration.kind == "github":
        github_integration = GitHubIntegration(integration)
        if github_integration.access_token_expired():
            github_integration.refresh_access_token()
    elif integration.kind == "firebase":
        firebase_integration = FirebaseIntegration(integration)
        if firebase_integration.access_token_expired():
            firebase_integration.refresh_access_token()

    return 0


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.INTEGRATIONS.value,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
)
@skip_team_scope_audit
def delete_ses_identity_if_unused(domain: str) -> None:
    from posthog.models.integration import Integration

    # Re-check at execution time: the domain may have been re-added since this
    # task was enqueued, and deleting the identity would break the new sender.
    if Integration.objects.filter(kind="email", config__domain=domain).exists():
        return

    SESProvider().delete_identity(domain)


@shared_task(ignore_result=True, queue=CeleryQueue.INTEGRATIONS.value)
@skip_team_scope_audit
def push_vercel_secrets(team_id: int) -> None:
    from posthog.models.team import Team

    from ee.vercel.integration import VercelIntegration

    team = Team.objects.get(id=team_id)
    VercelIntegration.push_secrets_to_vercel(team)
