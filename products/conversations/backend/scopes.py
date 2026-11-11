"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="posthog_support",
        name="PostHog support",
        plural="PostHog support tickets",
        description="Tickets you open and follow with the PostHog support team, which show as sent by you.",
        group="Organization & account",
        docs_url="https://posthog.com/docs/support",
        actions=("write",),
    ),
    ScopeDoc(
        object="support_ticket",
        name="Support ticket",
        plural="support tickets",
        description="Support tickets fetched through the external ticket API, used only by project secret API keys.",
        group="Customers & support",
        docs_url="https://posthog.com/docs/support",
    ),
    ScopeDoc(
        object="ticket",
        name="Ticket",
        plural="tickets",
        description="Support tickets, including their messages, notes, status, assignment, saved views, and macros.",
        group="Customers & support",
        docs_url="https://posthog.com/docs/support",
    ),
)
