import structlog
from celery import shared_task

from posthog.models.integration import Integration
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.team import Team

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def backfill_vercel_connectable_resources() -> None:
    """One-shot task to create missing Integration resources for connectable Vercel installations."""
    from ee.vercel.client import VercelAPIClient
    from ee.vercel.integration import VercelIntegration

    installations = OrganizationIntegration.objects.filter(
        kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
    )

    for installation in installations:
        org = installation.organization
        teams_with_resources = set(
            Integration.objects.filter(
                team__organization=org,
                kind=Integration.IntegrationKind.VERCEL,
            ).values_list("team_id", flat=True)
        )

        teams_without_resources = Team.objects.filter(organization=org).exclude(pk__in=teams_with_resources)

        for team in teams_without_resources:
            try:
                resource, created = Integration.objects.get_or_create(
                    team=team,
                    kind=Integration.IntegrationKind.VERCEL,
                    integration_id=str(team.pk),
                    defaults={"config": {"type": "connectable"}},
                )
                if not created:
                    continue

                access_token = installation.sensitive_config.get("credentials", {}).get("access_token")
                if not access_token or not installation.integration_id:
                    continue

                client = VercelAPIClient(bearer_token=access_token)
                client.import_resource(
                    integration_config_id=installation.integration_id,
                    resource_id=str(resource.pk),
                    product_id="posthog",
                    name=team.name,
                    secrets=VercelIntegration._build_secrets(team),
                )

                VercelIntegration.bulk_sync_feature_flags_to_vercel(team)

                logger.info(
                    "Backfilled Vercel resource for connectable installation",
                    team_id=team.pk,
                    installation_id=installation.integration_id,
                    integration="vercel",
                )
            except Exception:
                logger.exception(
                    "Failed to backfill Vercel resource",
                    team_id=team.pk,
                    integration="vercel",
                )
