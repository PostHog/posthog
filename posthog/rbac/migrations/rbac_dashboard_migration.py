from typing import Literal

from django.db import transaction
from django.db.models import Q

import structlog

from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization, OrganizationMembership

from products.access_control.backend.facade.user_access_control import ordered_access_levels
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import RoleMembership
from products.dashboards.backend.models.dashboard import Dashboard

logger = structlog.get_logger(__name__)


def _has_dashboard_role_access(
    dashboard: Dashboard,
    organization: Organization,
    user_id: int,
) -> bool:
    if not organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS):
        return False

    role_ids = (
        RoleMembership.objects.filter(user_id=user_id, role__organization_id=organization.id)
        .valid_for_authorization()
        .values("role_id")
    )
    return (
        AccessControl.objects.filter(
            team_id=dashboard.team_id,
            resource="dashboard",
            organization_member__isnull=True,
            role_id__in=role_ids,
        )
        .filter(Q(resource_id=str(dashboard.id)) | Q(resource_id__isnull=True))
        .exists()
    )


def _ensure_dashboard_access_control(
    dashboard: Dashboard,
    organization_member: OrganizationMembership | None,
    access_level: Literal["viewer", "editor"],
) -> None:
    access_control = AccessControl.objects.filter(
        team_id=dashboard.team_id,
        resource="dashboard",
        resource_id=str(dashboard.id),
        organization_member=organization_member,
        role__isnull=True,
    ).first()
    if access_control is None:
        AccessControl.objects.create(
            team_id=dashboard.team_id,
            access_level=access_level,
            resource="dashboard",
            resource_id=str(dashboard.id),
            organization_member=organization_member,
        )
        return

    if access_control.access_level in ordered_access_levels("dashboard"):
        return

    logger.warning(
        "Replacing invalid dashboard access level during migration",
        access_control_id=access_control.id,
        invalid_access_level=access_control.access_level,
        replacement_access_level=access_level,
    )
    access_control.access_level = access_level
    access_control.save(update_fields=["access_level"])


def rbac_dashboard_access_control_migration(organization_id: int) -> None:
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
                    _ensure_dashboard_access_control(
                        dashboard,
                        organization_member=None,
                        access_level="viewer",
                    )

                    # Convert dashboard privileges to access control entries
                    try:
                        from ee.models import DashboardPrivilege

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

                                if _has_dashboard_role_access(dashboard, organization, privilege.user_id):
                                    logger.info(
                                        "Preserving role-based dashboard access for collaborator",
                                        dashboard_id=dashboard.id,
                                        user_id=privilege.user_id,
                                    )
                                else:
                                    _ensure_dashboard_access_control(
                                        dashboard,
                                        organization_member=org_membership,
                                        access_level="editor",
                                    )

                                privilege.delete()
                                logger.info(
                                    "Migrated dashboard privilege to access control",
                                    dashboard_id=dashboard.id,
                                    user_id=privilege.user.id,
                                    team_id=dashboard.team_id,
                                )

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
