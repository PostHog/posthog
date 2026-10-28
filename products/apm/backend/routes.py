from posthog.api.routing import RouterRegistry

from products.apm.backend.presentation.views import EndpointsHealthViewSet, ServicesHealthViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"apm/services", ServicesHealthViewSet, "project_apm_services", ["team_id"])
    routers.projects.register(r"apm/endpoints", EndpointsHealthViewSet, "project_apm_endpoints", ["team_id"])
