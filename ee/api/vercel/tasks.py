import structlog
from celery import shared_task

from posthog.models.integration import Integration
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
@skip_team_scope_audit
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


@shared_task(ignore_result=True)
@skip_team_scope_audit
def sync_vercel_connect_feature_flags(team_id: int) -> None:
    """Push a project's feature flags to Vercel after a connectable account link.

    The number of Vercel requests grows with the project's flag count, so the link
    endpoint answers first and the flags go out here.
    """
    from ee.vercel.integration import VercelIntegration

    team = Team.objects.filter(pk=team_id).first()
    if not team:
        logger.error(
            "Project gone before the Vercel flag sync ran",
            team_id=team_id,
            integration="vercel",
        )
        return

    VercelIntegration.bulk_sync_feature_flags_to_vercel(team)
