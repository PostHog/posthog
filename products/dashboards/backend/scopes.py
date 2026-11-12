"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="dashboard",
        name="Dashboard",
        plural="dashboards",
        description="Dashboards, including their tiles, text cards, widgets, and layout, and running the insights on them.",
        group="Product analytics",
        docs_url="https://posthog.com/docs/product-analytics/dashboards",
    ),
    ScopeDoc(
        object="dashboard_template",
        name="Dashboard template",
        plural="dashboard templates",
        description="Dashboard templates, including their JSON schema and copying templates between projects.",
        group="Product analytics",
        docs_url="https://posthog.com/docs/product-analytics/dashboards",
    ),
)
