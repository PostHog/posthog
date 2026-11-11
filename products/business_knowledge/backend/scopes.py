"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="business_knowledge",
        name="Business knowledge",
        plural="business knowledge",
        description="Business knowledge sources, documents, and settings that give PostHog AI context, plus gap suggestions.",
        group="AI & context management tools",
        docs_url="https://posthog.com/docs/business-knowledge",
    ),
)
