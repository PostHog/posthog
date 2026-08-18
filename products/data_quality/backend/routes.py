from posthog.api.routing import RouterRegistry

from products.data_quality.backend.presentation.views import DataQualityCheckViewSet, DataQualitySuiteRunViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"data_quality/checks",
        DataQualityCheckViewSet,
        "environment_data_quality_checks",
        ["team_id"],
    )
    routers.projects.register(
        r"data_quality/check_suite_runs",
        DataQualitySuiteRunViewSet,
        "environment_data_quality_check_suite_runs",
        ["team_id"],
    )
