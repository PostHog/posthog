from posthog.api.routing import RouterRegistry

from products.business_knowledge.backend.api import (
    BusinessKnowledgeSettingsViewSet,
    KnowledgeDocumentViewSet,
    KnowledgeGapSuggestionViewSet,
    KnowledgeSourceViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"business_knowledge/sources",
        KnowledgeSourceViewSet,
        "project_business_knowledge_sources",
        ["team_id"],
    )
    routers.projects.register(
        r"business_knowledge/documents",
        KnowledgeDocumentViewSet,
        "project_business_knowledge_documents",
        ["team_id"],
    )
    routers.projects.register(
        r"business_knowledge/gap_suggestions",
        KnowledgeGapSuggestionViewSet,
        "project_business_knowledge_gap_suggestions",
        ["team_id"],
    )
    # After the nested resource prefixes so `sources`/`documents`/`gap_suggestions`
    # are not captured as a detail pk of this viewset.
    routers.projects.register(
        r"business_knowledge",
        BusinessKnowledgeSettingsViewSet,
        "project_business_knowledge_settings",
        ["team_id"],
    )
