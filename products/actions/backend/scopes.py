"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="action",
        name="Action",
        plural="actions",
        description="Actions, the named combinations of events and page elements, including where they are referenced.",
        group="Events, people & data model",
        docs_url="https://posthog.com/docs/data/actions",
    ),
)
