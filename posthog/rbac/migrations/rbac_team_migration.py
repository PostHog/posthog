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
        members = ExplicitTeamMembership.objects.filter(team_id=team.id)
        for member in members:
            AccessControl.objects.create(
                team=team,
                access_level="admin" if member.level == ExplicitTeamMembership.Level.ADMIN else "member",
                resource="project",
                resource_id=team.id,
                organization_member=member.user,
            )
            logger.info("Created RBAC access control", team_id=team.id, member_id=member.id)

    logger.info("Finished RBAC team migrations", team_id=team_id)
