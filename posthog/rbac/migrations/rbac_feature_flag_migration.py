from django.db import transaction

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team

from ee.models.feature_flag_role_access import FeatureFlagRoleAccess
from ee.models.rbac.access_control import AccessControl
from ee.models.rbac.organization_resource_access import OrganizationResourceAccess
from ee.models.rbac.role import Role

logger = structlog.get_logger(__name__)


# This migration is used to migrate over feature flag permissions to the new RBAC system
# It will find all feature flag role access for the organization and migrate them over to the new system
# It will also remove the feature flag role access so we know it's been migrated
def rbac_feature_flag_role_access_migration(organization_id: str):
    try:
        logger.info("Starting RBAC feature flag role access migration", organization_id=organization_id)

        with transaction.atomic():
            try:
                # All feature flags for the organization where it's view only (access level 21)
                # Basically if this exists then all flags in the organization are by default view only
                # And only other roles / specific opt in via FeatureFlagRoleAccess give edit access
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

                # Now that we've done the org level ones we can look at the feature flag role access
                # These a basically specific ones applied to a role and a feature flag
                feature_flag_role_access = FeatureFlagRoleAccess.objects.filter(role__organization_id=organization_id)
                for role_access in feature_flag_role_access:
                    # Create access control for the feature flag role access
                    feature_flag = role_access.feature_flag
                    role = role_access.role
                    AccessControl.objects.create(
                        team=feature_flag.team,
                        access_level="editor",
                        resource="feature_flag",
                        resource_id=feature_flag.id,
                        role=role,
                    )
                    # Remove the feature flag role access (so we know it's been migrated)
                    role_access.delete()

                    logger.info(
                        "Migrated RBAC feature flag access control",
                        organization_id=organization_id,
                        feature_flag_id=feature_flag.id,
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
