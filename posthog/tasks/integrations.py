from celery import shared_task

from posthog.models.integration import GitHubIntegration, GoogleCloudIntegration
from posthog.tasks.utils import CeleryQueue


@shared_task(ignore_result=True, queue=CeleryQueue.INTEGRATIONS.value)
def refresh_integrations() -> int:
    from posthog.models.integration import Integration, OauthIntegration

    oauth_integrations = Integration.objects.filter(kind__in=OauthIntegration.supported_kinds).all()

    for integration in oauth_integrations:
        oauth_integration = OauthIntegration(integration)

        if oauth_integration.access_token_expired():
            refresh_integration.delay(integration.id)

    gcloud_integrations = Integration.objects.filter(kind__in=GoogleCloudIntegration.supported_kinds).all()

    for integration in gcloud_integrations:
        gcloud_integration = GoogleCloudIntegration(integration)

        if gcloud_integration.access_token_expired():
            refresh_integration.delay(integration.id)

    github_integrations = Integration.objects.filter(kind="github").all()

    for integration in github_integrations:
        github_integration = GitHubIntegration(integration)

        if github_integration.access_token_expired():
            refresh_integration.delay(integration.id)

    return 0


@shared_task(ignore_result=True, queue=CeleryQueue.INTEGRATIONS.value)
def refresh_integration(id: int) -> int:
    from posthog.models.integration import Integration, OauthIntegration

    integration = Integration.objects.get(id=id)

    if integration.kind in OauthIntegration.supported_kinds:
        oauth_integration = OauthIntegration(integration)
        oauth_integration.refresh_access_token()
    elif integration.kind in GoogleCloudIntegration.supported_kinds:
        gcloud_integration = GoogleCloudIntegration(integration)
        gcloud_integration.refresh_access_token()
    elif integration.kind == "github":
        github_integration = GitHubIntegration(integration)
        github_integration.refresh_access_token()

    return 0
