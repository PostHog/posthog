from posthog.api.routing import RouterRegistry

from products.data_quality.backend.presentation.views import DataQualityCheckViewSet, DataQualityRunViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"data_quality_checks", DataQualityCheckViewSet, "project_data_quality_checks", ["team_id"]
    )
    routers.projects.register(r"data_quality_runs", DataQualityRunViewSet, "project_data_quality_runs", ["team_id"])
