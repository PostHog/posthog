from posthog.dataclasses import frozen


@frozen
class ProductFamily:
    key: str
    label: str


@frozen
class ProductUsageDefinition:
    key: str
    label: str
    family: str
    events: tuple[str, ...]


PRODUCT_FAMILIES: tuple[ProductFamily, ...] = (
    ProductFamily(key="product_cs", label="Product & CS"),
    ProductFamily(key="engineering", label="Engineering"),
    ProductFamily(key="data_ai", label="Data & AI"),
)

POSTHOG_PRODUCTS: tuple[ProductUsageDefinition, ...] = (
    ProductUsageDefinition(
        key="product_analytics",
        label="Product analytics",
        family="product_cs",
        events=(
            "insight created",
            "insight saved",
            "insight updated",
            "insight analyzed",
            "dashboard created",
            "dashboard updated",
            "dashboard tile added",
        ),
    ),
    ProductUsageDefinition(
        key="web_analytics",
        label="Web analytics",
        family="product_cs",
        events=(
            "web analytics filter applied",
            "web analytics date range changed",
            "web analytics compare toggled",
            "web analytics conversion goal set",
        ),
    ),
    ProductUsageDefinition(
        key="session_replay",
        label="Session replay",
        family="product_cs",
        events=("recording viewed", "recording analyzed"),
    ),
    ProductUsageDefinition(
        key="surveys",
        label="Surveys",
        family="product_cs",
        events=("survey created", "survey edited", "survey launched", "survey resumed", "survey stopped"),
    ),
    ProductUsageDefinition(
        key="customer_analytics",
        label="Customer analytics",
        family="product_cs",
        events=(
            "customer analytics accounts searched",
            "customer analytics accounts filter changed",
            "customer analytics accounts account opened",
            "customer analytics account tab viewed",
            "customer analytics dashboard events saved",
        ),
    ),
    ProductUsageDefinition(
        key="workflows",
        label="Workflows",
        family="product_cs",
        events=(
            "workflows workflow created",
            "workflow draft created",
            "workflow step added",
            "workflow enabled",
            "workflows schedule saved",
        ),
    ),
    ProductUsageDefinition(
        key="feature_flags",
        label="Feature flags",
        family="engineering",
        events=("feature flag created", "feature flag updated"),
    ),
    ProductUsageDefinition(
        key="experiments",
        label="Experiments",
        family="engineering",
        events=(
            "experiment created",
            "experiment updated",
            "experiment launched",
            "experiment stopped",
            "experiment completed",
            "experiment variant shipped",
        ),
    ),
    ProductUsageDefinition(
        key="error_tracking",
        label="Error tracking",
        family="engineering",
        events=(
            "error_tracking_issue_changed",
            "error_tracking_issue_update_status",
            "error_tracking_issue_update_assignee",
            "error_tracking_issue_bulk_resolve",
        ),
    ),
    ProductUsageDefinition(
        key="logs",
        label="Logs",
        family="engineering",
        events=("logs query executed", "logs filter changed", "logs live tail started"),
    ),
    ProductUsageDefinition(
        key="tracing",
        label="Tracing & metrics",
        family="engineering",
        events=("tracing query executed", "tracing trace opened", "tracing filter changed"),
    ),
    ProductUsageDefinition(
        key="inbox",
        label="Self-driving inbox",
        family="engineering",
        events=("Inbox report opened", "Inbox report action", "signals_scout_report_edited", "Signal source connected"),
    ),
    ProductUsageDefinition(
        key="data_warehouse",
        label="Data warehouse",
        family="data_ai",
        events=("data warehouse source created", "warehouse source saved", "view created", "materialized view created"),
    ),
    ProductUsageDefinition(
        key="data_pipelines",
        label="Data pipelines",
        family="data_ai",
        events=("hog function saved", "hog function draft published", "batch export backfill created"),
    ),
    ProductUsageDefinition(
        key="endpoints",
        label="Endpoints",
        family="data_ai",
        events=("endpoint created", "endpoint executed"),
    ),
    ProductUsageDefinition(
        key="ai_observability",
        label="AI observability",
        family="data_ai",
        events=(
            "llma single trace loaded",
            "llma evaluation created",
            "llma prompt created",
            "llma dataset created",
            "llm analytics evaluation executed",
        ),
    ),
    ProductUsageDefinition(
        key="mcp_analytics",
        label="MCP analytics",
        family="data_ai",
        events=(),
    ),
    ProductUsageDefinition(
        key="posthog_ai",
        label="PostHog AI",
        family="data_ai",
        events=("chat with ai", "max conversation turn completed", "ai tool executed"),
    ),
)
