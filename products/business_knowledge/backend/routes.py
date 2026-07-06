from posthog.api.routing import RouterRegistry

from products.business_knowledge.backend.api import (
    KnowledgeDocumentViewSet,
    KnowledgeGapSuggestionViewSet,
    KnowledgeSourceViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"business_knowledge/sources",
        KnowledgeSourceViewSet,
        "environment_business_knowledge_sources",
        ["team_id"],
    )
    routers.projects.register(
        r"business_knowledge/documents",
        KnowledgeDocumentViewSet,
        "environment_business_knowledge_documents",
        ["team_id"],
    )
    routers.projects.register(
        r"business_knowledge/gap_suggestions",
        KnowledgeGapSuggestionViewSet,
        "environment_business_knowledge_gap_suggestions",
        ["team_id"],
    )
