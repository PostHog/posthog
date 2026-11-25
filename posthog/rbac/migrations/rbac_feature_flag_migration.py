from django.db import transaction

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.organization_resource_access import OrganizationResourceAccess
from products.access_control.backend.models.role import Role

logger = structlog.get_logger(__name__)


# This migration is used to migrate over feature flag permissions to the new RBAC system
# It will find the organization's view-only feature flag access and migrate it over to the new system
# It will also remove the organization resource access so we know it's been migrated
def rbac_feature_flag_role_access_migration(organization_id: str):
    try:
        logger.info("Starting RBAC feature flag role access migration", organization_id=organization_id)

        with transaction.atomic():
            try:
                # All feature flags for the organization where it's view only (access level 21)
                # Basically if this exists then all flags in the organization are by default view only
                # And only roles with edit access to feature flags can edit them
                organization_resource_access = OrganizationResourceAccess.objects.filter(
                    organization_id=organization_id,
                    resource="feature flags",  # note this is plural and space
                    access_level=OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW,
                )
                if organization_resource_access.exists():
                    # Add view only access to the feature flag resources for each team in the organization
                    for team in Team.objects.filter(organization_id=organization_id):
                        AccessControl.objects.create(
                            # Note: no user or role or resource_id so it's project wide and applies to all flags
                            team=team,
                            access_level="viewer",
                            resource="feature_flag",
                        )
                    # Remove the organization resource access (so we know it's been migrated)
                    organization_resource_access.delete()

                    # Then we want to look at all roles where the feature flag role is edit level to apply those to all flags, we need
                    # to do this if the organization resource access is view only
                    editor_roles = Role.objects.filter(
                        organization_id=organization_id,
                        feature_flags_access_level=OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT,
                    )
                    for role in editor_roles:
                        for team in Team.objects.filter(organization_id=organization_id):
                            AccessControl.objects.create(
                                team=team,
                                access_level="editor",
                                resource="feature_flag",
                                role=role,
                            )
            except Exception as e:
                logger.error(
                    "Error during RBAC feature flag transaction",
                    organization_id=organization_id,
                    error=str(e),
                    exc_info=True,
                )
                capture_exception(e)
                raise  # Re-raise to rollback transaction

        logger.info("Finished RBAC feature flag role access migration", organization_id=organization_id)

    except Exception as e:
        logger.error(
            "Failed to complete RBAC feature flag migration",
            organization_id=organization_id,
            error=str(e),
            exc_info=True,
        )
        capture_exception(e)
        raise  # Re-raise the exception to indicate migration failure
