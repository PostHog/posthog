from posthog.api.routing import RouterRegistry

from products.data_catalog.backend.presentation.views import (
    CertificationViewSet,
    MetricViewSet,
    RelationshipProposalViewSet,
)
from products.data_quality.backend.presentation.views import MetricCheckViewSet, MetricSuiteRunViewSet


def register_routes(routers: RouterRegistry) -> None:
    metrics_router = routers.projects.register(
        r"data_catalog/metrics", MetricViewSet, "environment_data_catalog_metrics", ["team_id"]
    )
    metrics_router.register(r"checks", MetricCheckViewSet, "project_metric_checks", ["team_id", "metric_id"])
    metrics_router.register(
        r"check_suite_runs", MetricSuiteRunViewSet, "project_metric_check_suite_runs", ["team_id", "metric_id"]
    )
    routers.projects.register(
        r"data_catalog/certifications",
        CertificationViewSet,
        "environment_data_catalog_certifications",
        ["team_id"],
    )
    routers.projects.register(
        r"data_catalog/relationship_proposals",
        RelationshipProposalViewSet,
        "environment_data_catalog_relationship_proposals",
        ["team_id"],
    )
