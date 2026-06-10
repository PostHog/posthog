from posthog.api.routing import RouterRegistry

from products.business_knowledge.backend.api import KnowledgeSourceViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"business_knowledge/sources",
        KnowledgeSourceViewSet,
        "environment_business_knowledge_sources",
        ["team_id"],
    )
