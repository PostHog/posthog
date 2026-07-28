from posthog.api.routing import RouterRegistry

from products.data_catalog.backend.presentation.views import (
    CertificationViewSet,
    MetricViewSet,
    RelationshipProposalViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"data_catalog/metrics", MetricViewSet, "environment_data_catalog_metrics", ["team_id"])
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
