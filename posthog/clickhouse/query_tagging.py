# This module is responsible for adding tags/metadata to outgoing clickhouse queries in a thread-safe manner
import os
import sys
import uuid
import types
import contextvars
from collections.abc import Generator
from contextlib import contextmanager, suppress
from enum import StrEnum
from typing import TYPE_CHECKING, Any, NotRequired, Optional, TypedDict, assert_never

if TYPE_CHECKING:
    from posthog.models.team import Team

# from posthog.clickhouse.client.connection import Workload
# from posthog.schema_enums import PersonsOnEventsMode
import structlog
from cachetools import cached
from pydantic import BaseModel, ConfigDict

from posthog.schema_enums import NodeKind, ProductKey

logger = structlog.get_logger(__name__)


class AccessMethod(StrEnum):
    PERSONAL_API_KEY = "personal_api_key"
    OAUTH = "oauth"
    SHARING_TOKEN = "sharing_token"
    ID_JAG = "id_jag"
    PROJECT_SECRET_API_KEY = "project_secret_api_key"
    TEAM_SECRET_TOKEN = "team_secret_token"


# OAuth and sharing-token deliberately excluded: OAuth is user-consented, sharing-token is public read-only.
_API_KEY_ACCESS_METHODS: frozenset[AccessMethod] = frozenset(
    {
        AccessMethod.PERSONAL_API_KEY,
        AccessMethod.PROJECT_SECRET_API_KEY,
        AccessMethod.TEAM_SECRET_TOKEN,
    }
)


def is_api_key_access_method(access_method: AccessMethod | str | None) -> bool:
    return access_method in _API_KEY_ACCESS_METHODS


class Product(StrEnum):
    API = "api"
    BATCH_EXPORT = "batch_export"
    COHORTS = "cohorts"
    CONVERSATIONS = "conversations"
    CUSTOMER_ANALYTICS = "customer_analytics"
    ENDPOINTS = "endpoints"
    ENGINEERING_ANALYTICS = "engineering_analytics"
    ERROR_TRACKING = "error_tracking"
    EXPERIMENTS = "experiments"
    FEATURE_FLAGS = "feature_flags"
    GROUP_ANALYTICS = "group_analytics"
    GROWTH = "growth"  # growth-team activation/lifecycle jobs (e.g. production-event detection)
    INGESTION = "ingestion"
    LLM_ANALYTICS = "llm_analytics"
    LOGS = "logs"
    MARKETING_ANALYTICS = "marketing_analytics"
    MAX_AI = "max_ai"
    METRICS = "metrics"
    MCP = "mcp"  # queries originating through the MCP server (agent tool calls)
    MCP_ANALYTICS = "mcp_analytics"  # queries from the MCP analytics product (insights, dashboards, sessions)
    MESSAGING = "messaging"
    MOBILE_REPLAY = "mobile_replay"
    NOTEBOOKS = "notebooks"
    PIPELINE_DESTINATIONS = "pipeline_destinations"
    PLATFORM_AND_SUPPORT = "platform_and_support"
    POSTHOG_CODE = "posthog_code"
    PRODUCT_ANALYTICS = "product_analytics"
    REPLAY = "replay"
    REPLAY_VISION = "replay_vision"
    REVENUE_ANALYTICS = "revenue_analytics"
    SDK_HEALTH = "sdk_health"
    SESSION_SUMMARY = "session_summary"
    SIGNALS = "signals"
    SURVEYS = "surveys"
    USER_INTERVIEWS = "user_interviews"
    WAREHOUSE = "warehouse"
    WEB_ANALYTICS = "web_analytics"
    WORKFLOWS = "workflows"

    BILLING = "billing"
    INTERNAL = "internal"  # for internal use only


class Feature(StrEnum):
    ACCOUNTS = "accounts"
    ALERTING = "alerting"
    BACKFILL = "backfill"
    BEHAVIORAL_COHORTS = "behavioral_cohorts"
    COHORT = "cohort"
    QUERY = "query"  # customer-facing queries only
    DEBUG_QUERY = "debug_query"  # /debug/query and related internal engineering tooling
    DIGEST = "digest"
    INSIGHT = "insight"
    DASHBOARD = "dashboard"
    CACHE_WARMUP = "cache_warmup"
    DATA_MODELING = "data_modeling"
    HEALTH_CHECK = "health_check"
    IMPORT_PIPELINE = "import_pipeline"
    PREAGGREGATION = "preaggregation"
    DATA_DELETION = "data_deletion"
    ENRICHMENT = "enrichment"  # background tasks that derive/sync data (not customer-facing)
    EVENT_FILTERS = "event_filters"
    SCHEMA_INTROSPECTION = "schema_introspection"
    # Specific scenes that fan out into multiple ad-hoc queries; tagged separately so query
    # usage analysis can attribute load to the originating product surface.
    EVENT_DEFINITION_SCENE = "event_definition_scene"
    PROPERTY_DEFINITION_SCENE = "property_definition_scene"
    EXPLORE_EVENTS_SCENE = "explore_events_scene"
    # Specific endpoints whose load is worth analysing on its own. The `/events/values` endpoint
    # is hit from every taxonomic property-value picker across the app, so attribution by scene
    # would be misleading; tagging by endpoint name keeps the signal honest.
    EVENTS_VALUES_API = "events_values_api"
    USAGE_REPORT = "usage_report"
    BILLING_ETL = "billing_etl"
    QUOTA_LIMITING = "quota_limiting"
    MIGRATION = "migration"
    MANAGEMENT_COMMAND = "management_command"
    # Endpoints product features
    ENDPOINT_EXECUTION = "endpoint_execution"  # external API callers (personal_api_key or oauth)
    ENDPOINT_PLAYGROUND = "endpoint_playground"  # frontend Playground tab (browser session auth)
    ENDPOINT_LAST_EXECUTION = "endpoint_last_execution"  # Usage tab query_log lookup
    POSTHOG_AI = "posthog_ai"
    MCP = "mcp"
    SEMANTIC_SEARCH = "semantic_search"


class FallbackTags(TypedDict):
    product: NotRequired[Product]
    feature: NotRequired[Feature]


# Scene keys come from frontend `activeSceneId` — the manifest-registered key for the route
# (e.g. `EndpointScene` for `/endpoints/:name`, `EndpointsScene` for `/endpoints`). This map
# is *not* exhaustive over the frontend `Scene` enum: pulling Scene into the generated schema
# would churn it every time a scene is added. Three categories below — scenes we attribute,
# container scenes (`None`, defer to kind), and everything else falls through to the kind
# fallback. The `None` rows double as breadcrumbs so the absence of a common scene is loud.
SCENE_TO_TAGS: dict[str, FallbackTags | None] = {
    "Cohort": {"product": Product.COHORTS, "feature": Feature.COHORT},
    "EndpointScene": {"product": Product.ENDPOINTS, "feature": Feature.QUERY},
    "EndpointsScene": {"product": Product.ENDPOINTS, "feature": Feature.QUERY},
    "EngineeringAnalytics": {"product": Product.ENGINEERING_ANALYTICS, "feature": Feature.QUERY},
    "Logs": {"product": Product.LOGS, "feature": Feature.QUERY},
    "Metrics": {"product": Product.METRICS, "feature": Feature.QUERY},
    "EventDefinition": {"product": Product.PRODUCT_ANALYTICS, "feature": Feature.EVENT_DEFINITION_SCENE},
    "EventDefinitionEdit": {"product": Product.PRODUCT_ANALYTICS, "feature": Feature.EVENT_DEFINITION_SCENE},
    "EventDefinitions": {"product": Product.PRODUCT_ANALYTICS, "feature": Feature.EVENT_DEFINITION_SCENE},
    "SQLEditor": {"product": Product.WAREHOUSE, "feature": Feature.QUERY},
    "PropertyDefinition": {"product": Product.PRODUCT_ANALYTICS, "feature": Feature.PROPERTY_DEFINITION_SCENE},
    "PropertyDefinitionEdit": {"product": Product.PRODUCT_ANALYTICS, "feature": Feature.PROPERTY_DEFINITION_SCENE},
    "PropertyDefinitions": {"product": Product.PRODUCT_ANALYTICS, "feature": Feature.PROPERTY_DEFINITION_SCENE},
    "ExploreEvents": {"product": Product.PRODUCT_ANALYTICS, "feature": Feature.EXPLORE_EVENTS_SCENE},
    # Container scenes — host arbitrary query kinds, so let the kind fallback decide.
    "Dashboard": None,
    "Dashboards": None,
    "Insight": None,
    "Notebook": None,
    "Notebooks": None,
    "DebugQuery": None,
    "Max": None,
    "WebAnalytics": None,
}


def kind_fallback_tags(kind: NodeKind) -> FallbackTags | None:
    """Exhaustive — `assert_never(kind)` makes pyright/mypy fail when a new NodeKind has no
    case arm. Return `None` for kinds that exist but shouldn't drive product attribution."""
    match kind:
        case (
            NodeKind.TRENDS_QUERY
            | NodeKind.FUNNELS_QUERY
            | NodeKind.RETENTION_QUERY
            | NodeKind.PATHS_QUERY
            | NodeKind.STICKINESS_QUERY
            | NodeKind.LIFECYCLE_QUERY
            | NodeKind.EVENTS_QUERY
            | NodeKind.CALENDAR_HEATMAP_QUERY
            | NodeKind.SESSIONS_QUERY
            | NodeKind.SESSIONS_TIMELINE_QUERY
            | NodeKind.STICKINESS_ACTORS_QUERY
        ):
            return {"product": Product.PRODUCT_ANALYTICS}
        case (
            NodeKind.WEB_OVERVIEW_QUERY
            | NodeKind.WEB_STATS_TABLE_QUERY
            | NodeKind.WEB_GOALS_QUERY
            | NodeKind.WEB_EXTERNAL_CLICKS_TABLE_QUERY
            | NodeKind.WEB_PAGE_URL_SEARCH_QUERY
            | NodeKind.WEB_VITALS_QUERY
            | NodeKind.WEB_VITALS_PATH_BREAKDOWN_QUERY
            | NodeKind.SESSION_ATTRIBUTION_EXPLORER_QUERY
            | NodeKind.WEB_NOTABLE_CHANGES_QUERY
            | NodeKind.WEB_ANALYTICS_EXTERNAL_SUMMARY_QUERY
        ):
            return {"product": Product.WEB_ANALYTICS}
        case (
            NodeKind.ERROR_TRACKING_QUERY
            | NodeKind.ERROR_TRACKING_ISSUE_CORRELATION_QUERY
            | NodeKind.ERROR_TRACKING_SIMILAR_ISSUES_QUERY
            | NodeKind.ERROR_TRACKING_BREAKDOWNS_QUERY
        ):
            return {"product": Product.ERROR_TRACKING}
        case NodeKind.LOGS_QUERY | NodeKind.LOG_ATTRIBUTES_QUERY | NodeKind.LOG_VALUES_QUERY:
            return {"product": Product.LOGS}
        case NodeKind.RECORDINGS_QUERY | NodeKind.SESSION_BATCH_EVENTS_QUERY:
            return {"product": Product.REPLAY}
        case (
            NodeKind.ENDPOINTS_USAGE_OVERVIEW_QUERY
            | NodeKind.ENDPOINTS_USAGE_TABLE_QUERY
            | NodeKind.ENDPOINTS_USAGE_TRENDS_QUERY
        ):
            return {"product": Product.ENDPOINTS}
        case (
            NodeKind.EXPERIMENT_QUERY
            | NodeKind.EXPERIMENT_TRENDS_QUERY
            | NodeKind.EXPERIMENT_FUNNELS_QUERY
            | NodeKind.EXPERIMENT_EXPOSURE_QUERY
            | NodeKind.EXPERIMENT_ACTORS_QUERY
            | NodeKind.EXPERIMENT_METRIC
            | NodeKind.EXPERIMENT_EVENT_EXPOSURE_CONFIG
            | NodeKind.EXPERIMENT_DATA_WAREHOUSE_NODE
        ):
            return {"product": Product.EXPERIMENTS}
        case (
            NodeKind.TRACE_QUERY
            | NodeKind.TRACES_QUERY
            | NodeKind.SESSION_QUERY
            | NodeKind.TRACE_NEIGHBORS_QUERY
            | NodeKind.TRACE_SPANS_QUERY
            | NodeKind.TRACE_SPANS_AGGREGATION_QUERY
            | NodeKind.TRACE_SPANS_TREE_QUERY
            | NodeKind.TRACE_SPANS_ATTRIBUTE_BREAKDOWN_QUERY
            | NodeKind.TRACE_SPANS_SYMBOL_STATS_QUERY
        ):
            return {"product": Product.LLM_ANALYTICS}
        case (
            NodeKind.VECTOR_SEARCH_QUERY
            | NodeKind.DOCUMENT_SIMILARITY_QUERY
            | NodeKind.SUGGESTED_QUESTIONS_QUERY
            | NodeKind.TEAM_TAXONOMY_QUERY
            | NodeKind.EVENT_TAXONOMY_QUERY
            | NodeKind.ACTORS_PROPERTY_TAXONOMY_QUERY
        ):
            return {"product": Product.MAX_AI}
        case (
            NodeKind.REVENUE_ANALYTICS_GROSS_REVENUE_QUERY
            | NodeKind.REVENUE_ANALYTICS_MRR_QUERY
            | NodeKind.REVENUE_ANALYTICS_METRICS_QUERY
            | NodeKind.REVENUE_ANALYTICS_OVERVIEW_QUERY
            | NodeKind.REVENUE_ANALYTICS_TOP_CUSTOMERS_QUERY
            | NodeKind.REVENUE_EXAMPLE_EVENTS_QUERY
            | NodeKind.REVENUE_EXAMPLE_DATA_WAREHOUSE_TABLES_QUERY
        ):
            return {"product": Product.REVENUE_ANALYTICS}
        case (
            NodeKind.MARKETING_ANALYTICS_TABLE_QUERY
            | NodeKind.MARKETING_ANALYTICS_AGGREGATED_QUERY
            | NodeKind.NON_INTEGRATED_CONVERSIONS_TABLE_QUERY
        ):
            return {"product": Product.MARKETING_ANALYTICS}
        case (
            NodeKind.MCP_HARNESS_BREAKDOWN_QUERY
            | NodeKind.MCP_TOOL_TOP_USERS_QUERY
            | NodeKind.MCP_TOOL_FAILURES_QUERY
            | NodeKind.MCP_TOOL_STATS_QUERY
            | NodeKind.MCP_TOOL_DAILY_STATS_QUERY
            | NodeKind.MCP_TOOL_DESCRIPTIONS_QUERY
            | NodeKind.MCP_TOOL_SAMPLE_INTENTS_QUERY
            | NodeKind.MCP_TOOL_NEIGHBORS_QUERY
        ):
            return {"product": Product.MCP_ANALYTICS}
        case (
            # not attributable on their own
            NodeKind.HOG_QL_QUERY
            | NodeKind.HOG_QL_METADATA
            | NodeKind.HOG_QL_AUTOCOMPLETE
            | NodeKind.HOG_QUERY
            | NodeKind.DATABASE_SCHEMA_QUERY
            | NodeKind.PROPERTY_VALUES_QUERY
            | NodeKind.USAGE_METRICS_QUERY
            | NodeKind.ACCOUNTS_QUERY
            # drill-downs — caller's product is what matters
            | NodeKind.ACTORS_QUERY
            | NodeKind.GROUPS_QUERY
            | NodeKind.INSIGHT_ACTORS_QUERY
            | NodeKind.INSIGHT_ACTORS_QUERY_OPTIONS
            | NodeKind.FUNNELS_ACTORS_QUERY
            | NodeKind.FUNNEL_CORRELATION_QUERY
            | NodeKind.FUNNEL_CORRELATION_ACTORS_QUERY
            # data-source nodes, not full queries
            | NodeKind.EVENTS_NODE
            | NodeKind.GROUP_NODE
            | NodeKind.ACTIONS_NODE
            | NodeKind.PERSONS_NODE
            | NodeKind.DATA_WAREHOUSE_NODE
            | NodeKind.FUNNELS_DATA_WAREHOUSE_NODE
            | NodeKind.LIFECYCLE_DATA_WAREHOUSE_NODE
            | NodeKind.DATA_TABLE_NODE
            | NodeKind.DATA_VISUALIZATION_NODE
            | NodeKind.SAVED_INSIGHT_NODE
            | NodeKind.INSIGHT_VIZ_NODE
        ):
            return None
    assert_never(kind)


class HogQLFeatures(BaseModel):
    """Tables and event filters extracted from a HogQL AST — feeds product
    attribution in ``add_fallback_query_tags`` for ``kind=HogQLQuery``."""

    tables: list[str] = []
    events: list[str] = []

    model_config = ConfigDict(validate_assignment=True)


class TemporalTags(BaseModel):
    """
    Tags for temporalio workflows and activities.
    """

    workflow_namespace: Optional[str] = None
    workflow_type: Optional[str] = None
    workflow_id: Optional[str] = None
    workflow_run_id: Optional[str] = None
    activity_type: Optional[str] = None
    activity_id: Optional[str] = None
    attempt: Optional[int] = None

    model_config = ConfigDict(validate_assignment=True, use_enum_values=True)


class DagsterTags(BaseModel):
    """
    Tags for Dagster runs

    Check: https://docs.dagster.io/api/dagster/internals#dagster.DagsterRun
    """

    job_name: Optional[str] = None
    run_id: Optional[str] = None
    tags: Optional[dict[str, str]] = None
    root_run_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    job_snapshot_id: Optional[str] = None
    execution_plan_snapshot_id: Optional[str] = None

    op_name: Optional[str] = None
    asset_key: Optional[str] = None


class QueryTags(BaseModel):
    team_id: Optional[int] = None
    user_id: Optional[int] = None
    access_method: Optional[AccessMethod] = None
    api_key_mask: Optional[str] = None
    api_key_label: Optional[str] = None
    org_id: Optional[uuid.UUID] = None
    product: Optional[Product | ProductKey] = None

    # at this moment: request for HTTP request, celery, dagster and temporal are used, please don't use others.
    kind: Optional[str] = None
    id: Optional[str] = None
    session_id: Optional[str] = None

    # temporalio tags
    temporal: Optional[TemporalTags] = None
    # dagster specific tags
    dagster: Optional[DagsterTags] = None

    query: Optional[object] = None
    query_settings: Optional[object] = None
    query_time_range_days: Optional[int] = None
    query_type: Optional[str] = None

    rate_limit_bypass: Optional[int] = None
    rate_limit_wait_ms: Optional[int] = None
    kill_switch: Optional[str] = None

    route_id: Optional[str] = None
    workload: Optional[str] = None  # enum connection.Workload
    dashboard_id: Optional[int] = None
    insight_id: Optional[int] = None
    exported_asset_id: Optional[int] = None
    export_format: Optional[str] = None
    chargeable: Optional[int] = None
    request_name: Optional[str] = None
    name: Optional[str] = None
    endpoint_version: Optional[int] = None  # Endpoints, the product
    endpoint_materialization_behind: Optional[bool] = (
        None  # set when a materialized endpoint is past its data_freshness SLA
    )

    http_referer: Optional[str] = None
    http_request_id: Optional[uuid.UUID] = None
    http_user_agent: Optional[str] = None

    # frontend UI context (from QueryLogTags)
    scene: Optional[str] = None

    alert_config_id: Optional[uuid.UUID] = None
    # Cadence and query shape of the alert that triggered this run, tagged at evaluation
    # so query_log cost can be grouped by frequency (real_time / every_15_minutes / ...)
    # and by config type (TrendsAlertConfig vs HogQLAlertConfig) without joining to Postgres.
    alert_calculation_interval: Optional[str] = None
    alert_config_type: Optional[str] = None
    batch_export_id: Optional[uuid.UUID] = None
    cache_key: Optional[str] = None
    celery_task_id: Optional[uuid.UUID] = None
    clickhouse_exception_type: Optional[str] = None
    client_query_id: Optional[str] = None
    cohort_id: Optional[int] = None
    # lazy-computation / preaggregation builds: the time window a single build INSERT covers (ISO).
    # Generic across products (experiments, marketing, web analytics) since they share the executor.
    precompute_window_start: Optional[str] = None
    precompute_window_end: Optional[str] = None
    entity_math: Optional[list[str]] = None

    # replays
    replay_playlist_id: Optional[int] = None

    # ai events rollout
    ai_query_source: Optional[str] = None

    ai_data_processing_approved: Optional[bool] = None

    # experiments
    experiment_feature_flag_key: Optional[str] = None
    experiment_id: Optional[int] = None
    experiment_name: Optional[str] = None
    experiment_is_data_warehouse_query: Optional[bool] = None
    experiment_metric_uuid: Optional[str] = None
    experiment_metric_name: Optional[str] = None
    experiment_metric_type: Optional[str] = None  # "mean", "funnel", "ratio", "retention"
    experiment_funnel_order_type: Optional[str] = None  # funnel metrics only: "ordered", "unordered", "strict"
    # DEPRECATED: alias of experiment_exposures_path, kept so external tooling keeps working.
    experiment_execution_path: Optional[str] = None  # "direct_scan" or "precomputed"
    experiment_exposures_path: Optional[str] = None  # "direct_scan" or "precomputed"
    experiment_metric_events_path: Optional[str] = None  # "direct_scan", "precomputed", or "not_applicable"
    experiment_query_surface: Optional[str] = None  # "metric", "exposures_timeseries", "actors", "precompute_build"
    experiment_precompute_table: Optional[str] = None  # on precompute_build rows: "exposures" or "metric_events"
    # Why precompute was not used (set on the metric read). One of "override_direct", "team_disabled",
    # "min_runtime", "data_warehouse"; None/absent when precompute was attempted (so a direct path then
    # means the build failed or wasn't ready — derivable from the precompute_build sub-queries).
    experiment_precompute_skip_reason: Optional[str] = None
    # Analysis window of the read (ISO), for the query-performance UI. The build sub-queries carry their
    # own per-chunk window in the generic precompute_window_start/end fields above.
    experiment_scan_date_from: Optional[str] = None
    experiment_scan_date_to: Optional[str] = None
    # Shared id linking a top-level query to its precompute-build sub-queries. Generated once per
    # top-level evaluation; sub-queries inherit it through the tag context. Lets the query-performance
    # UI group the (synchronous) build INSERTs under the read that triggered them.
    experiment_query_group_id: Optional[uuid.UUID] = None
    experiment_actors_query_step: Optional[int] = None  # funnel step for actors query
    experiment_actors_query_variant: Optional[str] = None  # variant filter for actors query
    experiment_actors_query_includes_recordings: Optional[bool] = None  # whether recordings are included

    feature: Optional[Feature] = None
    filter: Optional[object] = None
    filter_by_type: Optional[list[str]] = None
    breakdown_by: Optional[list[str]] = None

    # data warehouse
    trend_volume_display: Optional[str] = None
    table_id: Optional[uuid.UUID] = None
    warehouse_query: Optional[bool] = None

    trend_volume_type: Optional[str] = None

    has_joins: Optional[bool] = None
    has_json_operations: Optional[bool] = None

    # True when the query embeds a user-supplied HogQL string; used to split user vs platform errors in system.query_log.
    contains_user_hogql: Optional[bool] = None

    hogql_features: Optional[HogQLFeatures] = None

    modifiers: Optional[object] = None
    number_of_entities: Optional[int] = None
    person_on_events_mode: Optional[str] = None  # PersonsOnEventsMode

    timings: Optional[dict[str, float]] = None
    execution_mode: Optional[str] = None
    trigger: Optional[str] = None

    # used by billing
    usage_report: Optional[str] = None

    user_email: Optional[str] = None

    is_impersonated: Optional[bool] = None

    # request source and MCP metadata
    source: Optional[str] = None
    mcp_user_agent: Optional[str] = None
    mcp_client_name: Optional[str] = None
    mcp_client_version: Optional[str] = None
    mcp_protocol_version: Optional[str] = None
    mcp_oauth_client_name: Optional[str] = None

    # caller source location (set automatically in sync_execute via stack inspection)
    source_file: Optional[str] = None
    source_line: Optional[int] = None

    # constant query tags
    git_commit: Optional[str] = None
    container_hostname: Optional[str] = None
    service_name: Optional[str] = None

    model_config = ConfigDict(validate_assignment=True, use_enum_values=True)

    def update(self, **kwargs):
        for field, value in kwargs.items():
            setattr(self, field, value)

    def with_temporal(self, temporal_tags: TemporalTags):
        self.kind = "temporal"
        self.temporal = temporal_tags

    def with_dagster(self, dagster_tags: DagsterTags):
        """Tags for dagster runs and activities."""
        self.kind = "dagster"
        self.dagster = dagster_tags

    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=True)


query_tags: contextvars.ContextVar = contextvars.ContextVar("query_tags")


@cached(cache={})
def __get_constant_tags() -> dict[str, str]:
    # import locally to avoid circular imports
    from posthog.settings import CONTAINER_HOSTNAME, OTEL_SERVICE_NAME, TEST

    if TEST:
        return {"git_commit": "test", "container_hostname": "test", "service_name": "test"}

    from posthog.git import get_git_commit_short

    return {
        "git_commit": get_git_commit_short() or "",
        "container_hostname": CONTAINER_HOSTNAME,
        "service_name": OTEL_SERVICE_NAME or "",
    }


def create_base_tags(**kwargs) -> QueryTags:
    return QueryTags(**{**kwargs, **__get_constant_tags()})


def get_query_tags() -> QueryTags:
    try:
        qt = query_tags.get()
    except LookupError:
        qt = create_base_tags()
        query_tags.set(qt)
    return qt


def get_query_tag_value(key: str) -> Optional[Any]:
    try:
        return getattr(get_query_tags(), key)
    except (AttributeError, KeyError):
        return None


# Tag snapshots are isolated copy-on-write: every mutation goes through a top-level attribute
# assignment on a fresh shallow copy (see update/with_temporal/with_dagster), and nested tag
# objects are only ever replaced, never mutated in place. That makes shallow model_copy()
# sufficient for isolation — deep copies here were the dominant cost of tag_queries, which runs
# on every request and every ClickHouse query. Keep that invariant when adding new tag helpers.


def update_tags(new_query_tags: QueryTags):
    current_tags = get_query_tags()
    updated_tags = current_tags.model_copy()
    updated_tags.update(**new_query_tags.model_dump(exclude_none=True))
    query_tags.set(updated_tags)


def tag_queries(**kwargs) -> None:
    """
    The purpose of tag_queries is to pass additional context for ClickHouse executed queries. The tags
    are serialized into ClickHouse' system.query_log.log_comment column.

    :param kwargs: Key->value pairs of tags to be set.
    """
    current_tags = get_query_tags()
    updated_tags = current_tags.model_copy()
    updated_tags.update(**kwargs)
    query_tags.set(updated_tags)


def tag_authentication(
    *,
    access_method: AccessMethod,
    team_id: int | None,
    user_id: int | None = None,
    api_key_mask: str | None = None,
    api_key_label: str | None = None,
) -> None:
    """Single funnel for authenticator query tagging — add new auth tags here, not in each authenticator."""
    tag_queries(
        user_id=user_id,
        team_id=team_id,
        access_method=access_method,
        api_key_mask=api_key_mask,
        api_key_label=api_key_label,
    )


def tag_contains_user_hogql() -> None:
    """Mark the current query as embedding a user-supplied HogQL string; used to separate user vs platform errors in system.query_log.

    Idempotent — safe to call inside hot loops (recursive ``property_to_expr``, breakdown
    iteration, ``@property`` accessors) since the early-return skips the ``model_copy``
    inside ``tag_queries`` after the first call per query context.
    """
    if get_query_tag_value("contains_user_hogql"):
        return
    tag_queries(contains_user_hogql=True)


def get_team_query_tags(team: "Team") -> dict[str, Any]:
    from posthog.models.organization import Organization

    tags: dict[str, Any] = {"team_id": team.pk}
    try:
        organization = team.organization
        tags["org_id"] = organization.pk
        tags["ai_data_processing_approved"] = organization.is_ai_data_processing_approved
    except Organization.DoesNotExist:
        logger.warning("get_team_query_tags_org_not_found", team_id=team.pk)
    return tags


def clear_tag(key):
    with suppress(LookupError):
        current_tags = query_tags.get()
        updated_tags = current_tags.model_copy()
        setattr(updated_tags, key, None)
        query_tags.set(updated_tags)


def reset_query_tags():
    query_tags.set(create_base_tags())


def _apply_fallback_tags(tags: QueryTags, mapped: FallbackTags) -> None:
    if tags.product is None and "product" in mapped:
        tags.product = mapped["product"]
    if tags.feature is None and "feature" in mapped:
        tags.feature = mapped["feature"]


# Event-level matches pinpoint a single product; consulted before tables since they're more specific.
_EVENT_TO_TAGS: tuple[tuple[frozenset[str], FallbackTags], ...] = (
    (
        frozenset({"$ai_generation", "$ai_span", "$ai_trace", "$ai_embedding", "$ai_metric", "$ai_feedback"}),
        {"product": Product.LLM_ANALYTICS},
    ),
    (frozenset({"$exception"}), {"product": Product.ERROR_TRACKING}),
    (frozenset({"$web_vitals"}), {"product": Product.WEB_ANALYTICS}),
    (frozenset({"$feature_flag_called"}), {"product": Product.FEATURE_FLAGS}),
)

# Union of every event the fallback can match — exposed so HogQLFeatureExtractor can use it as
# its allow-list without duplicating the names. Adding a new mapping to _EVENT_TO_TAGS
# automatically widens what the extractor records.
EVENT_TAG_MATCHERS: frozenset[str] = frozenset().union(*(matchers for matchers, _ in _EVENT_TO_TAGS))

# Table-level fallbacks — only consulted if no event filter narrowed things down.
_TABLE_TO_TAGS: tuple[tuple[frozenset[str], FallbackTags], ...] = (
    (frozenset({"session_replay_events", "raw_session_replay_events"}), {"product": Product.REPLAY}),
    (frozenset({"logs", "log_attributes"}), {"product": Product.LOGS}),
    (frozenset({"metrics", "metric_attributes"}), {"product": Product.METRICS}),
    (frozenset({"events"}), {"product": Product.PRODUCT_ANALYTICS}),
)


def _query_structure_fallback_tags(query: object, max_depth: int = 16) -> FallbackTags | None:
    """Walk a query's `source` chain to the first node whose kind maps to a product.

    Wrapper / drill-down nodes (DataTableNode, ActorsQuery, InsightActorsQuery, …) map to None in
    `kind_fallback_tags` — "caller's product is what matters". When one of them runs as the
    top-level request (e.g. "open as new insight" from an actors modal) there is no caller, so we
    descend into `source` to find the wrapped insight (e.g. RetentionQuery → product_analytics).

    Reads the canonical `kind` from `tags.query`, so it also resolves runners that pass a non-NodeKind
    `query_type` label (e.g. marketing analytics' "marketing_analytics_table_query"). Accepts the raw
    query dict stored on `tags.query` or a pydantic node.
    """
    current = query
    for _ in range(max_depth):
        if isinstance(current, dict):
            kind_value, source = current.get("kind"), current.get("source")
        else:
            kind_value, source = getattr(current, "kind", None), getattr(current, "source", None)
        if isinstance(kind_value, str):
            try:
                kind = NodeKind(kind_value)
            except ValueError:
                kind = None
            if kind is not None and (mapped := kind_fallback_tags(kind)) is not None:
                return mapped
        if source is None:
            return None
        current = source
    return None


def add_fallback_query_tags(tags: QueryTags) -> None:
    """Order: scene → kind → query structure → hogql features (HogQLQuery only) → mcp source. Never overrides set values."""
    if tags.scene and (scene_mapped := SCENE_TO_TAGS.get(tags.scene)) is not None:
        _apply_fallback_tags(tags, scene_mapped)

    if tags.product is None and tags.query_type:
        try:
            kind = NodeKind(tags.query_type)
        except ValueError:
            kind = None
        if kind is not None and (kind_mapped := kind_fallback_tags(kind)) is not None:
            _apply_fallback_tags(tags, kind_mapped)

    if tags.product is None and tags.query is not None:
        if (query_mapped := _query_structure_fallback_tags(tags.query)) is not None:
            _apply_fallback_tags(tags, query_mapped)

    if (
        tags.product is None
        and tags.query_type == NodeKind.HOG_QL_QUERY.value
        and (features := tags.hogql_features) is not None
    ):
        events_set, tables_set = set(features.events), set(features.tables)
        features_mapped = next(
            (m for matchers, m in _EVENT_TO_TAGS if events_set & matchers),
            None,
        ) or next(
            (m for matchers, m in _TABLE_TO_TAGS if tables_set & matchers),
            None,
        )
        if features_mapped is not None:
            _apply_fallback_tags(tags, features_mapped)

    from posthog.event_usage import EventSource

    if tags.product is None and tags.source == EventSource.MCP:
        tags.product = Product.MCP


class QueryCounter:
    SLOW_QUERY_THRESHOLD_S = 0.05

    def __init__(self):
        self.total_query_time = 0.0
        self.count = 0
        self.max_query_time = 0.0
        self.slow_count = 0

    @property
    def query_time_ms(self):
        return self.total_query_time * 1000

    @property
    def max_query_time_ms(self):
        return self.max_query_time * 1000

    def __call__(self, execute, *args, **kwargs):
        import time

        start_time = time.perf_counter()

        try:
            return execute(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - start_time
            self.total_query_time += elapsed
            self.count += 1
            if elapsed > self.max_query_time:
                self.max_query_time = elapsed
            if elapsed > self.SLOW_QUERY_THRESHOLD_S:
                self.slow_count += 1


@contextmanager
def tags_context(**tags_to_set: Any) -> Generator[None]:
    """
    Context manager that saves all query tags on enter and restores them on exit.
    Optionally accepts key-value pairs to set after saving the original tags.

    Usage:
    ```python
    with tags_context(foo='bar', baz='qux'):
        # tags are saved, new tags are set
        # do stuff with tags
        # tags will be restored to original state after context
    ```
    """
    tags_copy: Optional[QueryTags] = None
    try:
        tags_copy = get_query_tags().model_copy()
        if tags_to_set:
            tag_queries(**tags_to_set)
        yield
    finally:
        if tags_copy:
            query_tags.set(tags_copy)


# Stack inspection for source_file / source_line tagging
_THIS_FILE = os.path.abspath(__file__)
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(_THIS_FILE), os.pardir, os.pardir))
_PROJECT_ROOT_PREFIX = _PROJECT_ROOT + os.sep

# Files/directories in the query execution infrastructure to skip when walking the stack
_SOURCE_SKIP_PREFIXES: tuple[str, ...] = (
    os.path.join(_PROJECT_ROOT, "posthog", "clickhouse", "client") + os.sep,
    _THIS_FILE,
    os.path.join(_PROJECT_ROOT, "posthog", "hogql", "query.py"),
    os.path.join(_PROJECT_ROOT, "posthog", "hogql_queries", "insights", "paginators.py"),
    os.path.join(_PROJECT_ROOT, "posthog", "queries", "insight.py"),
    os.path.join(_PROJECT_ROOT, "posthog", "utils.py"),
)

_MAX_CALLER_STACK_DEPTH = 30


def get_caller_source() -> tuple[Optional[str], Optional[int]]:
    """Walk the call stack to find the first caller outside of query execution infrastructure.

    Returns (source_file, source_line) where source_file is relative to the project root,
    or (None, None) if no suitable caller is found.
    """
    try:
        frame: Optional[types.FrameType] = sys._getframe(1)

        for _ in range(_MAX_CALLER_STACK_DEPTH):
            if frame is None:
                break

            filename = frame.f_code.co_filename

            # Only consider frames within the project
            if not filename.startswith(_PROJECT_ROOT_PREFIX):
                frame = frame.f_back
                continue

            # Skip query execution infrastructure
            if any(filename.startswith(prefix) for prefix in _SOURCE_SKIP_PREFIXES):
                frame = frame.f_back
                continue

            return filename[len(_PROJECT_ROOT_PREFIX) :], frame.f_lineno

        return None, None
    except Exception:
        return None, None
