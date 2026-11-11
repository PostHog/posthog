"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="account",
        name="Account",
        plural="accounts",
        description="Customer analytics accounts, their custom properties, relationships, notes, notebooks, and event streams.",
        group="Customers & support",
        docs_url="https://posthog.com/docs/customer-analytics/start-here",
    ),
    ScopeDoc(
        object="account_note",
        name="Account note",
        plural="account notes",
        description="Notes on Customer analytics accounts and their tags, without access to the rest of the account.",
        group="Customers & support",
        docs_url="https://posthog.com/docs/customer-analytics/start-here",
    ),
    ScopeDoc(
        object="customer_analytics",
        name="Customer analytics",
        plural="customer analytics",
        description="Customer analytics feature requests, product areas, account tracking rules, and Slack announcements.",
        group="Customers & support",
        docs_url="https://posthog.com/docs/customer-analytics/start-here",
    ),
    ScopeDoc(
        object="customer_journey",
        name="Customer journey",
        plural="customer journeys",
        description="Customer journeys in Customer analytics, each built on a saved insight.",
        group="Customers & support",
        docs_url="https://posthog.com/docs/customer-analytics/customer-journeys",
    ),
    ScopeDoc(
        object="customer_profile_config",
        name="Customer profile config",
        plural="customer profile configs",
        description="Layouts of the person and group profile pages in Customer analytics, including their content and sidebar.",
        group="Customers & support",
        docs_url="https://posthog.com/docs/customer-analytics/customer-profiles",
    ),
    ScopeDoc(
        object="customer_task",
        name="Customer task",
        plural="customer tasks",
        description="Customer tasks on accounts in Customer analytics, with status, assignee, due date, and activity history.",
        group="Customers & support",
        docs_url="https://posthog.com/docs/customer-analytics/start-here",
    ),
    ScopeDoc(
        object="usage_metric",
        name="Usage metric",
        plural="usage metrics",
        description="Customer analytics usage metrics that track how each account or group uses your product.",
        group="Customers & support",
        docs_url="https://posthog.com/docs/customer-analytics/usage-metrics",
    ),
)
