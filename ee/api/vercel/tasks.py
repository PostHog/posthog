import structlog
from celery import shared_task

from posthog.integrations import CrossTeamFilter, IntegrationManager
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
@skip_team_scope_audit
def backfill_vercel_connectable_resources() -> None:
    """One-shot task to create missing Integration resources for connectable Vercel installations."""
    from ee.vercel.client import VercelAPIClient
    from ee.vercel.integration import VercelIntegration, get_or_create_connectable_resource

    installations = OrganizationIntegration.objects.filter(
        kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
    )

    for installation in installations:
        if not installation.integration_id:
            continue
        org = installation.organization
        org_team_ids = Team.objects.filter(organization=org).values_list("id", flat=True)
        teams_with_resources = {
            row.team_id
            for row in IntegrationManager.vercel.oauth.list_across_teams(CrossTeamFilter(team_ids=tuple(org_team_ids)))
        }

        teams_without_resources = Team.objects.filter(organization=org).exclude(pk__in=teams_with_resources)

        for team in teams_without_resources:
            try:
                # A resource created without an import is skipped by every later run, so get the token first.
                # Ask for each team, because syncing the previous team's flags can outlast a token.
                access_token = VercelIntegration._get_access_token(installation)
                if not access_token:
                    continue

                resource, created = get_or_create_connectable_resource(team)
                if not created:
                    continue

                client = VercelAPIClient(bearer_token=access_token)
                client.import_resource(
                    integration_config_id=installation.integration_id,
                    resource_id=str(resource.id),
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
