from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.feature_flag_role_access import FeatureFlagRoleAccess
from products.access_control.backend.models.organization_resource_access import OrganizationResourceAccess
from products.access_control.backend.models.role import Role, RoleMembership
from products.access_control.backend.models.role_external_reference import RoleExternalReference


def test_access_control_models_keep_existing_database_tables() -> None:
    assert AccessControl._meta.db_table == "ee_accesscontrol"
    assert FeatureFlagRoleAccess._meta.db_table == "ee_featureflagroleaccess"
    assert OrganizationResourceAccess._meta.db_table == "ee_organizationresourceaccess"
    assert Role._meta.db_table == "ee_role"
    assert RoleMembership._meta.db_table == "ee_rolemembership"
    assert RoleExternalReference._meta.db_table == "posthog_roleexternalreference"
