from django.db import transaction
from posthog.models import Team
from ee.models.rbac.access_control import AccessControl
from ee.models.explicit_team_membership import ExplicitTeamMembership
import structlog

logger = structlog.get_logger(__name__)


def rbac_team_migrations(team_id: int):
    logger.info("Starting RBAC team migrations", team_id=team_id)

    with transaction.atomic():
        team = Team.objects.get(id=team_id)
        # Set the access control for the team
        AccessControl.objects.create(
            team=team,
            access_level="none",
            resource="project",
            resource_id=team.id,
        )

        # Get all members for the project
        team_memberships = ExplicitTeamMembership.objects.filter(team_id=team.id)
        for team_membership in team_memberships:
            AccessControl.objects.create(
                team=team,
                access_level="admin" if team_membership.level == ExplicitTeamMembership.Level.ADMIN else "member",
                resource="project",
                resource_id=team.id,
                organization_member=team_membership.parent_membership,
            )
            logger.info(
                "Created RBAC access control", team_id=team.id, user_id=team_membership.parent_membership.user.id
            )

    logger.info("Finished RBAC team migrations", team_id=team_id)
