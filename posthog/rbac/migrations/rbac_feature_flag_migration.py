from ee.models.rbac.access_control import AccessControl
from ee.models.feature_flag_role_access import FeatureFlagRoleAccess
from ee.models.rbac.organization_resource_access import OrganizationResourceAccess
from posthog.models.feature_flag import FeatureFlag
from ee.models.rbac.role import Role
from django.db import transaction
import structlog

logger = structlog.get_logger(__name__)


# This migration is used to migrate over feature flag permissions to the new RBAC system
# It will find all feature flag role access for the organization and migrate them over to the new system
# It will also remove the feature flag role access so we know it's been migrated
def rbac_feature_flag_role_access_migration(organization_id: str):
    logger.info("Starting RBAC feature flag role access migration", organization_id=organization_id)

    with transaction.atomic():
        # All feature flags for the organization where it's view only (access level 21)
        # Basically if this exists then all flags in the organization are by default view only
        # And only other roles / specific opt in via FeatureFlagRoleAccess give edit access
        organization_resource_access = OrganizationResourceAccess.objects.filter(
            organization_id=organization_id,
            resource="feature_flag",
            access_level=21,
        )
        if organization_resource_access.exists():
            # Add view only access to all feature flags for the organization
            for feature_flag in FeatureFlag.objects.filter(team__organization_id=organization_id):
                AccessControl.objects.create(
                    # Note: no user or role so it's project wide
                    team=feature_flag.team,
                    access_level="viewer",
                    resource="feature_flag",
                    resource_id=feature_flag.id,
                )

            # Then we want to look at all roles where the feature flag role is edit level to apply those to all flags, we need
            # to do this if the organization resource access is view only
            editor_roles = Role.objects.filter(organization_id=organization_id, feature_flags_access_level=37)
            for role in editor_roles:
                for feature_flag in FeatureFlag.objects.filter(team__organization_id=organization_id):
                    AccessControl.objects.create(
                        team=feature_flag.team,
                        access_level="editor",
                        resource="feature_flag",
                        resource_id=feature_flag.id,
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

    logger.info("Finished RBAC feature flag role access migration", organization_id=organization_id)
