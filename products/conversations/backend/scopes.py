"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

# Held out of SCOPE_DOCS while `posthog_support` is omitted from the scope pickers, until the
# `posthog-support-agent-tickets` flag rolls out. At launch, move it back into SCOPE_DOCS and drop the
# omission in posthog/scopes/exposure.py.
POSTHOG_SUPPORT_SCOPE_DOC = ScopeDoc(
    object="posthog_support",
    name="PostHog support",
    plural="PostHog support tickets",
    description="Tickets you open and follow with the PostHog support team, which show as sent by you.",
    group="Organization & account",
    docs_url="https://posthog.com/docs/support",
)

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
