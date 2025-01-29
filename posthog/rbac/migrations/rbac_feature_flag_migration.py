from ee.models.rbac.access_control import AccessControl
from ee.models.feature_flag_role_access import FeatureFlagRoleAccess
from django.db import transaction
import structlog

logger = structlog.get_logger(__name__)


# This migration is used to migrate over feature flag permissions to the new RBAC system
# It will find all feature flag role access for the organization and migrate them over to the new system
# It will also remove the feature flag role access so we know it's been migrated
def rbac_feature_flag_role_access_migration(organization_id: str):
    logger.info("Starting RBAC feature flag role access migration", organization_id=organization_id)

    # Get feature flag role access for the organization
    feature_flag_role_access = FeatureFlagRoleAccess.objects.filter(role__organization_id=organization_id)

    with transaction.atomic():
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
