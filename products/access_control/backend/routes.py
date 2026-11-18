from posthog.api.routing import RouterRegistry

from products.access_control.backend.presentation.role import RoleMembershipViewSet, RoleViewSet


def register_routes(routers: RouterRegistry) -> None:
    roles = routers.organizations.register(
        r"roles",
        RoleViewSet,
        "organization_roles",
        ["organization_id"],
    )
    roles.register(
        r"role_memberships",
        RoleMembershipViewSet,
        "organization_role_memberships",
        ["organization_id", "role_id"],
    )
