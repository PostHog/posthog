from posthog.api.routing import RouterRegistry

from products.authz.backend.presentation.views import AuthzViewSet


def register_routes(routers: RouterRegistry) -> None:
    # Root-level because the endpoints describe the instance, not a project.
    routers.root.register(r"authz", AuthzViewSet, "authz")
