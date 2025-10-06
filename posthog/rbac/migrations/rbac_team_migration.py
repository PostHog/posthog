from django.db import transaction

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization, OrganizationMembership

from ee.models.explicit_team_membership import ExplicitTeamMembership
from ee.models.rbac.access_control import AccessControl

logger = structlog.get_logger(__name__)


# This migration is used to migrate over team permissions to the new RBAC system
# It will find all teams that have access control enabled and migrate them over to the new system
# It will also remove the access control from the team so we know it's been migrated
def rbac_team_access_control_migration(organization_id: int):
    logger.info("Starting RBAC team migrations", organization_id=organization_id)

    try:
        with transaction.atomic():
            organization = Organization.objects.get(id=organization_id)
            for team in organization.teams.all():
                try:
                    # Skip if access control is already disabled
                    if not team.access_control:
                        continue

                    # Create access control for the team
                    AccessControl.objects.create(
                        team=team,
                        access_level="none",
                        resource="project",
                        resource_id=team.id,
                    )

                    # Get all members for the project
                    team_memberships = ExplicitTeamMembership.objects.filter(
                        team_id=team.id,
                        # Make sure the user is active
                        parent_membership__user__is_active=True,
                        # Make sure their organization membership exists
                        parent_membership__organization__isnull=False,
                        # Only migrate members that are not admins in the organization
                        parent_membership__level__lt=OrganizationMembership.Level.ADMIN,
                    )
                    for team_membership in team_memberships:
                        try:
                            # Create access control for the team member
                            AccessControl.objects.create(
                                team=team,
                                access_level=(
                                    "admin" if team_membership.level == ExplicitTeamMembership.Level.ADMIN else "member"
                                ),
                                resource="project",
                                resource_id=team.id,
                                organization_member=team_membership.parent_membership,
                            )
                            # Remove the existing team membership
                            team_membership.delete()

                            logger.info(
                                "Migrated RBAC team access control",
                                organization_id=team.id,
                                user_id=team_membership.parent_membership.user.id,
                                team_id=team.id,
                            )
                        except Exception as e:
                            error_message = f"Failed to migrate team membership for team {team.id}"
                            logger.exception(error_message, exc_info=e)
                            capture_exception(
                                e,
                                additional_properties={
                                    "team_id": team.id,
                                    "organization_id": organization_id,
                                    "team_membership_id": team_membership.id,
                                },
                            )
                            raise

                    # Disable access control for the team (so we know it's been migrated)
                    team.access_control = False
                    team.save()
                    # Delete any left over explicit team memberships
                    ExplicitTeamMembership.objects.filter(team_id=team.id).delete()
                except Exception as e:
                    error_message = f"Failed to migrate team {team.id}"
                    logger.exception(error_message, exc_info=e)
                    capture_exception(e, additional_properties={"team_id": team.id, "organization_id": organization_id})
                    raise

        logger.info("Finished RBAC team migrations", organization_id=organization_id)
    except Exception as e:
        error_message = f"Failed to complete RBAC migration for organization {organization_id}"
        logger.exception(error_message, exc_info=e)
        capture_exception(e, additional_properties={"organization_id": organization_id})
        raise
