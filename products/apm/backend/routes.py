from posthog.api.routing import RouterRegistry

from products.apm.backend.presentation.views import ServicesHealthViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"apm/services", ServicesHealthViewSet, "project_apm_services", ["team_id"])
