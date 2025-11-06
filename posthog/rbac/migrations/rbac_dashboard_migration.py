from django.db import transaction

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.dashboard import Dashboard
from posthog.models.organization import Organization, OrganizationMembership

from products.enterprise.backend.models.rbac.access_control import AccessControl

logger = structlog.get_logger(__name__)


def rbac_dashboard_access_control_migration(organization_id: int):
    """
    This migration converts legacy dashboard permissions to the new RBAC system.

    It handles two cases:
    1. Dashboards with restriction_level=37 (ONLY_COLLABORATORS_CAN_EDIT):
       - Creates a default "view" access control entry
       - Changes restriction_level to 21 (EVERYONE_IN_PROJECT_CAN_EDIT)
    2. Dashboard privilege rows:
       - Converts each DashboardPrivilege to an AccessControl entry with "edit" access
       - Removes the original DashboardPrivilege entries
    """
    logger.info("Starting RBAC dashboard migrations", organization_id=organization_id)

    try:
        with transaction.atomic():
            organization = Organization.objects.get(id=organization_id)

            # Get dashboards that need migration (restriction level 37)
            team_ids = organization.teams.values_list("id", flat=True)
            restricted_dashboards = Dashboard.objects.filter(
                team_id__in=team_ids, restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
            )

            for dashboard in restricted_dashboards:
                try:
                    # Skip if access control already exists for this dashboard
                    if AccessControl.objects.filter(
                        team_id=dashboard.team_id,
                        resource="dashboard",
                        resource_id=str(dashboard.id),
                    ).exists():
                        logger.info(
                            "Skipping dashboard - access control already exists",
                            dashboard_id=dashboard.id,
                            team_id=dashboard.team_id,
                        )
                        continue

                    # Create default access control entry for the dashboard (view access for all)
                    AccessControl.objects.create(
                        team_id=dashboard.team_id,
                        access_level="viewer",
                        resource="dashboard",
                        resource_id=str(dashboard.id),
                    )

                    logger.info(
                        "Created default dashboard access control", dashboard_id=dashboard.id, team_id=dashboard.team_id
                    )

                    # Convert dashboard privileges to access control entries
                    try:
                        from products.enterprise.backend.models import DashboardPrivilege

                        dashboard_privileges = DashboardPrivilege.objects.filter(dashboard_id=dashboard.id)

                        for privilege in dashboard_privileges:
                            try:
                                # Find the organization membership for this user
                                org_membership = OrganizationMembership.objects.filter(
                                    user=privilege.user, organization=organization
                                ).first()

                                if not org_membership:
                                    logger.warning(
                                        "No organization membership found for user",
                                        user_id=privilege.user.id,
                                        dashboard_id=dashboard.id,
                                    )
                                    continue

                                # Create access control entry for the user with edit access
                                AccessControl.objects.create(
                                    team_id=dashboard.team_id,
                                    access_level="editor",
                                    resource="dashboard",
                                    resource_id=str(dashboard.id),
                                    organization_member=org_membership,
                                )

                                logger.info(
                                    "Migrated dashboard privilege to access control",
                                    dashboard_id=dashboard.id,
                                    user_id=privilege.user.id,
                                    team_id=dashboard.team_id,
                                )

                                # Remove the original privilege entry
                                privilege.delete()

                            except Exception as e:
                                error_message = f"Failed to migrate dashboard privilege for user {privilege.user.id}"
                                logger.exception(error_message, exc_info=e)
                                capture_exception(
                                    e,
                                    additional_properties={
                                        "dashboard_id": dashboard.id,
                                        "user_id": privilege.user.id,
                                        "organization_id": organization_id,
                                    },
                                )
                                raise

                    except ImportError:
                        # DashboardPrivilege model not available, skip privilege migration
                        logger.info("DashboardPrivilege model not available, skipping privilege migration")

                    # Update restriction level to EVERYONE_IN_PROJECT_CAN_EDIT (21)
                    dashboard.restriction_level = Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
                    dashboard.save(update_fields=["restriction_level"])

                    logger.info(
                        "Updated dashboard restriction level",
                        dashboard_id=dashboard.id,
                        new_restriction_level=dashboard.restriction_level,
                    )

                except Exception as e:
                    error_message = f"Failed to migrate dashboard {dashboard.id}"
                    logger.exception(error_message, exc_info=e)
                    capture_exception(
                        e, additional_properties={"dashboard_id": dashboard.id, "organization_id": organization_id}
                    )
                    raise

        logger.info("Finished RBAC dashboard migrations", organization_id=organization_id)
    except Exception as e:
        error_message = f"Failed to complete RBAC dashboard migration for organization {organization_id}"
        logger.exception(error_message, exc_info=e)
        capture_exception(e, additional_properties={"organization_id": organization_id})
        raise
