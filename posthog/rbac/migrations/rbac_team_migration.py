from django.db import transaction
from ee.models.rbac.access_control import AccessControl
from ee.models.explicit_team_membership import ExplicitTeamMembership
import structlog
from posthog.models.organization import Organization
logger = structlog.get_logger(__name__)


def rbac_team_access_control_migration(organization_id: int):
    logger.info("Starting RBAC team migrations", organization_id=organization_id)

    with transaction.atomic():
        organization = Organization.objects.get(id=organization_id)
        for team in organization.teams.all():
            
            # Migrate over team permissions if it's currently private
            if team.access_control:
                AccessControl.objects.create(
                    team=team,
                    access_level="none",
                    resource="project",
                    resource_id=team.id,
                )

                # Get all members for the project
                team_memberships = ExplicitTeamMembership.objects.filter(organization_id=team.id)
                for team_membership in team_memberships:
                    AccessControl.objects.create(
                        team=team,
                        access_level="admin" if team_membership.level == ExplicitTeamMembership.Level.ADMIN else "member",
                        resource="project",
                        resource_id=team.id,
                        organization_member=team_membership.parent_membership,
                    )
                    logger.info(
                        "Created RBAC access control", organization_id=team.id, user_id=team_membership.parent_membership.user.id
                    )

    logger.info("Finished RBAC team migrations", organization_id_id=organization_id)
