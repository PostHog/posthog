"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="alert",
        name="Alert",
        plural="alerts",
        description="Alerts on insights, metrics, and data warehouse sources, including thresholds, destinations, and snoozes.",
        group="Product analytics",
        docs_url="https://posthog.com/docs/alerts",
    ),
)
