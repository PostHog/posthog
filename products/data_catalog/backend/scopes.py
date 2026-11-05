"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="data_catalog",
        name="Data catalog",
        plural="data catalog",
        description="Data catalog metrics, certifications on warehouse tables and views, and proposed relationships between tables.",
        group="AI & context management tools",
        docs_url="https://posthog.com/docs/semantic-layer",
    ),
    ScopeDoc(
        object="data_catalog_approval",
        name="Data catalog approval",
        plural="data catalog approvals",
        description="Approving Data catalog metrics, certifying tables, and accepting relationships, so agents cannot self-approve.",
        group="AI & context management tools",
        docs_url="https://posthog.com/docs/semantic-layer/governance",
        actions=("write",),
    ),
)
