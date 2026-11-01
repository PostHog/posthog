from posthog.api.routing import RouterRegistry

from products.apm.backend.presentation.views import EndpointsHealthViewSet, ServiceMapViewSet, ServicesHealthViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"apm/services", ServicesHealthViewSet, "project_apm_services", ["team_id"])
    routers.projects.register(r"apm/endpoints", EndpointsHealthViewSet, "project_apm_endpoints", ["team_id"])
    routers.projects.register(r"apm/service_map", ServiceMapViewSet, "project_apm_service_map", ["team_id"])
