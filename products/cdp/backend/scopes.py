"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="hog_function",
        name="Hog function",
        plural="hog functions",
        description="Data pipeline destinations, transformations, and other Hog functions, plus their templates.",
        group="Data warehouse & pipelines",
        docs_url="https://posthog.com/docs/data-pipelines",
    ),
    ScopeDoc(
        object="plugin",
        name="Plugin",
        plural="plugins",
        description="Legacy apps (plugins), their configurations, and their logs.",
        group="Data warehouse & pipelines",
        docs_url="https://posthog.com/docs/data-pipelines",
    ),
    ScopeDoc(
        object="webhook",
        name="Webhook",
        plural="webhooks",
        description="REST hook subscriptions used by the Zapier integration to send matching events to a target URL.",
        group="Data warehouse & pipelines",
        docs_url="https://posthog.com/docs/libraries/zapier",
    ),
)
