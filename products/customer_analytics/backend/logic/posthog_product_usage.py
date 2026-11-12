from posthog.dataclasses import frozen

ENGAGED_SECONDS = 30
ENGAGED_MAX_SECONDS = 1800
REPLAY_WATCH_MS = 10000
REPLAY_WATCH_EVENT = "recording viewed summary"
PAGE_EVENTS = ("$pageview", "$pageleave")
STAFF_EMAIL_PATTERN = "%@posthog.com"


@frozen
class ProductUsageDefinition:
    key: str
    label: str
    sections: tuple[str, ...]
    actions: tuple[str, ...]


@frozen
class ProductGroup:
    key: str
    label: str
    products: tuple[str, ...]


@frozen
class ProductGrouping:
    key: str
    label: str
    groups: tuple[ProductGroup, ...]


POSTHOG_PRODUCTS: tuple[ProductUsageDefinition, ...] = (
    ProductUsageDefinition(
        key="pa",
        label="Product analytics",
        sections=(
            "insights",
            "dashboard",
            "dashboards",
            "cohorts",
            "cohort",
            "persons",
            "person",
            "groups",
            "events",
            "data-management",
            "data_management",
            "activity",
            "actions",
            "alerts",
            "notebooks",
        ),
        actions=(
            "insight analyzed",
            "insight created",
            "insight updated",
            "insight saved",
            "insight breakdown changed",
            "funnel step reordered",
            "insight person modal viewed",
            "correlation analyzed",
            "dashboard analyzed",
            "dashboard created",
            "dashboard updated",
            "dashboard tile added",
            "cohort created",
            "cohort updated",
            "action created",
            "annotation created",
            "alert created",
            "notebook created",
            "notebook content changed",
        ),
    ),
    ProductUsageDefinition(
        key="web",
        label="Web analytics",
        sections=("web", "web_analytics", "web-analytics", "marketing"),
        actions=(
            "web analytics filter applied",
            "web analytics filter removed",
            "web analytics date range changed",
            "web analytics compare toggled",
            "web analytics conversion goal set",
            "web_analytics_recording_opened",
            "web analytics share link copied",
        ),
    ),
    ProductUsageDefinition(
        key="replay",
        label="Session replay",
        sections=("replay", "replay-vision", "replay_vision", "recordings", "session-summaries", "session_summaries"),
        actions=(
            "recording playlist created",
            "replay_vision_scanner_created",
            "replay_vision_scanner_edited",
            "replay_vision_observation_viewed",
            "replay_vision_summarize_clicked",
            "replay_vision_inline_scan_requested",
        ),
    ),
    ProductUsageDefinition(
        key="heatmaps",
        label="Heatmaps",
        sections=("heatmaps", "toolbar"),
        actions=("in-app heatmap viewed", "in-app heatmap created", "in-app heatmap clickmap rendered"),
    ),
    ProductUsageDefinition(
        key="surveys",
        label="Surveys",
        sections=("surveys", "product_tours", "product-tours"),
        actions=(
            "survey created",
            "survey launched",
            "survey edited",
            "survey stopped",
            "survey resumed",
            "survey viewed",
            "survey consolidated results query completed",
        ),
    ),
    ProductUsageDefinition(
        key="customers",
        label="Customer analytics",
        sections=("customer_analytics", "customer-analytics", "revenue_analytics", "revenue-analytics"),
        actions=(),
    ),
    ProductUsageDefinition(
        key="flags",
        label="Feature flags",
        sections=("feature_flags", "feature-flags", "early_access_features", "early-access-features"),
        actions=(
            "feature flag created",
            "feature flag updated",
            "feature flag archived",
            "feature flag copied",
            "feature flag created in additional projects",
        ),
    ),
    ProductUsageDefinition(
        key="exp",
        label="Experiments",
        sections=("experiments",),
        actions=(
            "experiment created",
            "experiment launched",
            "experiment updated",
            "experiment completed",
            "experiment variant shipped",
            "experiment shared metric created",
        ),
    ),
    ProductUsageDefinition(
        key="errors",
        label="Error tracking",
        sections=("error_tracking", "error-tracking"),
        actions=(
            "error_tracking_issue_viewed",
            "error_tracking_issue_changed",
            "error_tracking_issue_update_status",
            "error_tracking_issue_update_assignee",
            "error_tracking_issue_update_severity",
            "error_tracking_issue_bulk_resolve",
            "error_tracking_alert_created",
            "error_tracking_suppression_rule_created",
            "error_tracking_stacktrace_explored",
            "viewed recordings from error tracking",
        ),
    ),
    ProductUsageDefinition(
        key="logs",
        label="Logs",
        sections=("logs",),
        actions=(
            "logs filter changed",
            "logs details opened",
            "logs log expanded",
            "logs live tail started",
            "logs patterns queried",
            "logs sql tab opened",
            "logs date range zoomed",
            "logs load more requested",
            "logs alert destination created",
        ),
    ),
    ProductUsageDefinition(
        key="tracing",
        label="Tracing & metrics",
        sections=("tracing", "metrics"),
        actions=(
            "tracing trace opened",
            "tracing trace fetched",
            "tracing filter changed",
            "tracing trace dialog opened",
            "tracing sql tab opened",
        ),
    ),
    ProductUsageDefinition(
        key="workflows",
        label="Workflows",
        sections=("workflows", "broadcasts"),
        actions=(
            "hog_flow_created",
            "hog_flow_activated",
            "hog_flow_draft_published",
            "hog_flow_graph_updated",
            "hog_flow_schedule_created",
            "hog_flow_batch_job_created",
            "workflow step added",
            "workflow enabled",
            "workflow draft created",
            "workflows tile canvas step added",
        ),
    ),
    ProductUsageDefinition(
        key="dwh",
        label="Data warehouse",
        sections=("sql", "data-warehouse", "models"),
        actions=(
            "data warehouse source created",
            "data warehouse source updated",
            "source created",
            "source reloaded",
            "warehouse source connect completed",
            "view created",
            "view updated",
            "sql-editor-accepted-suggestion",
            "sql-editor-fix-error-click",
            "sql-editor-schema-panel-opened",
            "sql-editor-history-modal-opened",
        ),
    ),
    ProductUsageDefinition(
        key="endpoints", label="Endpoints", sections=("endpoints",), actions=("endpoint created", "endpoint executed")
    ),
    ProductUsageDefinition(
        key="pipelines",
        label="Data pipelines",
        sections=("pipeline", "functions", "data-pipelines", "batch_exports", "batch-exports", "etl"),
        actions=("hog function saved", "batch export backfill created"),
    ),
    ProductUsageDefinition(
        key="llm",
        label="AI observability",
        sections=("ai-observability", "llm-analytics", "llm-observability", "ai-evals", "prompt-management"),
        actions=(
            "llma single trace loaded",
            "llma summarization generated",
            "llma prompt fetched",
            "llma prompt created",
            "llma prompt version published",
            "llma prompt label set",
            "llma evaluation created",
            "llma evaluation updated",
            "llma playground parameters configured",
            "llma skill version published",
            "llma clusters level changed",
            "llm evaluation template selected",
        ),
    ),
    ProductUsageDefinition(key="mcpa", label="MCP analytics", sections=("mcp-analytics",), actions=()),
    ProductUsageDefinition(
        key="ai",
        label="PostHog AI",
        sections=("ai", "skills"),
        actions=("chat with ai", "max conversation turn completed"),
    ),
    ProductUsageDefinition(
        key="support",
        label="Support",
        sections=("support",),
        actions=(
            "support ticket created",
            "support ticket updated",
            "support ticket composed",
            "support message sent",
            "support tickets bulk status updated",
            "support ticket deleted",
            "support setting changed",
            "support activation completed",
        ),
    ),
    ProductUsageDefinition(
        key="sd",
        label="Self-driving",
        sections=("inbox",),
        actions=(
            "Inbox report action",
            "Inbox report action completed",
            "Inbox report feedback",
            "Inbox settings changed",
            "Inbox triage started",
            "Scout action",
            "Scout config changed",
            "Scout suggestion created",
            "Scout chat started",
            "Signal source connected",
            "Signal source disabled",
            "Signal source filters changed",
            "Signal source steering changed",
        ),
    ),
    ProductUsageDefinition(
        key="semantic",
        label="Semantic layer",
        sections=("data-catalog",),
        actions=(
            "data catalog metric created",
            "data catalog metric updated",
            "data catalog metric approved",
            "data catalog metric run",
        ),
    ),
)

PRODUCT_GROUPINGS: tuple[ProductGrouping, ...] = (
    ProductGrouping(
        key="role",
        label="Roles",
        groups=(
            ProductGroup(
                key="product_cs",
                label="Product & CS",
                products=("pa", "web", "replay", "surveys", "customers", "workflows"),
            ),
            ProductGroup(
                key="engineering", label="Engineering", products=("flags", "exp", "errors", "logs", "tracing", "sd")
            ),
            ProductGroup(
                key="data_ai", label="Data & AI", products=("dwh", "pipelines", "endpoints", "llm", "mcpa", "ai")
            ),
        ),
    ),
    ProductGrouping(
        key="usecase",
        label="Use cases",
        groups=(
            ProductGroup(
                key="product_intelligence",
                label="Product Intelligence",
                products=("pa", "replay", "heatmaps", "surveys", "ai"),
            ),
            ProductGroup(key="release_engineering", label="Release Engineering", products=("flags", "exp", "sd")),
            ProductGroup(key="observability", label="Observability", products=("errors", "logs", "tracing")),
            ProductGroup(
                key="growth_marketing",
                label="Growth & Marketing",
                products=("web", "heatmaps", "surveys", "workflows", "pipelines"),
            ),
            ProductGroup(
                key="ai_llm_observability", label="AI/LLM Observability", products=("llm", "mcpa", "ai", "sd")
            ),
            ProductGroup(
                key="data_infrastructure",
                label="Data Infrastructure",
                products=("dwh", "pipelines", "endpoints", "semantic"),
            ),
            ProductGroup(
                key="customer_experience",
                label="Customer Experience",
                products=("support", "replay", "errors", "surveys", "workflows"),
            ),
        ),
    ),
)
