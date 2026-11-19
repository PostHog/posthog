from posthog.api.routing import RouterRegistry

from products.apm.backend.presentation.views import (
    DependenciesViewSet,
    DeploymentsViewSet,
    EndpointsHealthViewSet,
    EndpointTimeSpentViewSet,
    ServiceMapViewSet,
    ServicesHealthViewSet,
    ServiceUsageViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"apm/services", ServicesHealthViewSet, "project_apm_services", ["team_id"])
    routers.projects.register(r"apm/endpoints", EndpointsHealthViewSet, "project_apm_endpoints", ["team_id"])
    routers.projects.register(
        r"apm/endpoint_time_spent", EndpointTimeSpentViewSet, "project_apm_endpoint_time_spent", ["team_id"]
    )
    routers.projects.register(r"apm/service_map", ServiceMapViewSet, "project_apm_service_map", ["team_id"])
    routers.projects.register(r"apm/usage", ServiceUsageViewSet, "project_apm_usage", ["team_id"])
    routers.projects.register(r"apm/deployments", DeploymentsViewSet, "project_apm_deployments", ["team_id"])
    routers.projects.register(r"apm/dependencies", DependenciesViewSet, "project_apm_dependencies", ["team_id"])
