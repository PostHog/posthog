"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="cross_project_dashboard",
        name="Cross-project dashboard",
        plural="cross-project dashboards",
        description="Dashboards the organization owns that show insights from one or more projects, and their tiles.",
        group="Product analytics",
        organization_wide=True,
    ),
)
