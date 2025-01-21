from ee.models.rbac.access_control import AccessControl
from ee.models.feature_flag_role_access import FeatureFlagRoleAccess


def rbac_feature_flag_migrations(organization_id: str):
    # Get feature flag role access for the organization
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
