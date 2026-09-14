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
def sync_vercel_connect_link(organization_integration_id: str) -> None:
    """Register the resource on Vercel and push the project's flags after a connectable account link.

    The link endpoint returns as soon as the rows exist, so this work happens here instead of
    holding the request open for one Vercel call per feature flag.
    """
    from ee.vercel.client import VercelAPIClient
    from ee.vercel.integration import VercelIntegration

    try:
        # nosemgrep: idor-lookup-without-org (Celery task; the pk comes from the row the link endpoint just wrote)
        installation = OrganizationIntegration.objects.get(
            pk=organization_integration_id,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        )
    except OrganizationIntegration.DoesNotExist:
        logger.info(
            "Vercel installation gone before link sync ran",
            organization_integration_id=organization_integration_id,
            integration="vercel",
        )
        return

    env_mapping = installation.config.get("environment_mapping", {})
    production_team_id = env_mapping.get("production")
    access_token = installation.sensitive_config.get("credentials", {}).get("access_token")
    teams_by_id = {
        team.pk: team
        for team in Team.objects.filter(
            pk__in=[tid for tid in env_mapping.values() if tid is not None],
        )
    }
    production_team = teams_by_id.get(production_team_id)
    resource = Integration.objects.filter(team_id=production_team_id, kind=Integration.IntegrationKind.VERCEL).first()

    if not (access_token and installation.integration_id and production_team and resource):
        logger.error(
            "Cannot sync a Vercel link without an access token, an installation id, a production project and a resource",
            organization_integration_id=organization_integration_id,
            team_id=production_team_id,
            integration="vercel",
        )
        return

    secrets = VercelIntegration.build_connectable_secrets(
        production_team,
        teams_by_id.get(env_mapping.get("preview"), production_team),
        teams_by_id.get(env_mapping.get("development"), production_team),
    )

    client = VercelAPIClient(bearer_token=access_token)
    import_result = client.import_resource(
        integration_config_id=installation.integration_id,
        resource_id=str(resource.pk),
        product_id="posthog",
        name=production_team.name,
        secrets=secrets,
    )
    if not import_result.success:
        logger.error(
            "Failed to import resource to Vercel",
            error=import_result.error,
            installation_id=installation.integration_id,
            resource_id=str(resource.pk),
            integration="vercel",
        )

    VercelIntegration.bulk_sync_feature_flags_to_vercel(production_team)
