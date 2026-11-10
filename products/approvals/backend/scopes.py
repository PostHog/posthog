"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="approvals",
        name="Approvals",
        plural="approvals",
        description="Approval policies and change requests that gate changes, including approving, rejecting, or canceling them.",
        group="AI & context management tools",
        docs_url="https://posthog.com/docs/settings/approvals",
    ),
)
