"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="support_ticket",
        name="External ticket API",
        plural="tickets from the external ticket API",
        description="Single tickets fetched through the external ticket API, for project secret API keys only.",
        group="Customers & support",
        docs_url="https://posthog.com/docs/support",
    ),
    ScopeDoc(
        object="ticket",
        name="Support ticket",
        plural="support tickets",
        description="Support tickets, including their messages, notes, status, assignment, saved views, and macros.",
        group="Customers & support",
        docs_url="https://posthog.com/docs/support",
    ),
)
