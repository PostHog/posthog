from posthog.api.routing import RouterRegistry

from products.data_catalog.backend.presentation.views import MetricViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"data_catalog/metrics", MetricViewSet, "environment_data_catalog_metrics", ["team_id"])
