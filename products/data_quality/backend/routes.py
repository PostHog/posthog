from posthog.api.routing import RouterRegistry

from products.data_quality.backend.presentation.views import DataQualityCheckOverviewViewSet, DataQualityRunViewSet


def register_routes(routers: RouterRegistry) -> None:
    # The per-subject check surfaces are nested under their warehouse parent and registered by the
    # data_warehouse product. This one spans every subject, so it hangs off the project directly.
    routers.projects.register(
        r"data_quality_checks", DataQualityCheckOverviewViewSet, "project_data_quality_checks", ["team_id"]
    )
    routers.projects.register(r"data_quality_runs", DataQualityRunViewSet, "project_data_quality_runs", ["team_id"])
