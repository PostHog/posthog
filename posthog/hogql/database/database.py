import io
import copy
import pickle
import threading
import dataclasses
import pickletools
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from functools import cache
from typing import TYPE_CHECKING, Any, Literal, Optional, Union, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Prefetch, Q

import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.direct_sql_table import DirectSQLTable
from posthog.hogql.database.lazy_join_tags import (
    DATA_WAREHOUSE,
    DATA_WAREHOUSE_EXPERIMENTS,
    ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
    ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES,
    EVENTS_TO_SESSIONS_V2,
    EVENTS_TO_SESSIONS_V3,
    PERSON_DISTINCT_ID_OVERRIDES,
    PERSONS,
    REPLAY_TO_SESSIONS_V2,
    REPLAY_TO_SESSIONS_V3,
)
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    DecimalDatabaseField,
    ExpressionField,
    FieldOrTable,
    FieldTraverser,
    FloatDatabaseField,
    FunctionCallTable,
    IntegerDatabaseField,
    LazyJoin,
    SavedQuery,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    StructDatabaseField,
    Table,
    TableNode,
    UnknownDatabaseField,
    UUIDDatabaseField,
    VirtualTable,
)
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.database.postgres_utils import add_postgres_foreign_key_lazy_joins
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.database.schema.ai_events import AiEventsTable
from posthog.hogql.database.schema.app_metrics2 import AppMetrics2Table
from posthog.hogql.database.schema.channel_type import create_initial_channel_type, create_initial_domain_type
from posthog.hogql.database.schema.cohort_membership import CohortMembershipTable
from posthog.hogql.database.schema.cohort_people import CohortPeople, RawCohortPeople
from posthog.hogql.database.schema.document_embeddings import (
    HOGQL_MODEL_TABLES,
    DocumentEmbeddingsTable,
    RawDocumentEmbeddingsTable,
)
from posthog.hogql.database.schema.duckdb_table_functions import GenerateSeriesTable, RangeTable
from posthog.hogql.database.schema.error_tracking_fingerprint_issue_state import (
    ErrorTrackingFingerprintIssueStateTable,
    RawErrorTrackingFingerprintIssueStateTable,
)
from posthog.hogql.database.schema.error_tracking_issue_fingerprint_overrides import (
    ErrorTrackingIssueFingerprintOverridesTable,
    RawErrorTrackingIssueFingerprintOverridesTable,
)
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.exchange_rate import ExchangeRateTable
from posthog.hogql.database.schema.experiment_exposures_preaggregated import ExperimentExposuresPreaggregatedTable
from posthog.hogql.database.schema.experiment_metric_events_preaggregated import (
    ExperimentMetricEventsPreaggregatedTable,
)
from posthog.hogql.database.schema.groups import GroupsTable, RawGroupsTable
from posthog.hogql.database.schema.groups_revenue_analytics import GroupsRevenueAnalyticsTable
from posthog.hogql.database.schema.heatmaps import HeatmapsTable
from posthog.hogql.database.schema.hog_invocation_results import HogInvocationResultsTable
from posthog.hogql.database.schema.log_entries import (
    BatchExportLogEntriesTable,
    LogEntriesTable,
    ReplayConsoleLogsLogEntriesTable,
)
from posthog.hogql.database.schema.logs import LogAttributesTable, LogsKafkaMetricsTable, LogsTable
from posthog.hogql.database.schema.marketing_conversions_preaggregated import MarketingConversionsPreaggregatedTable
from posthog.hogql.database.schema.marketing_costs_preaggregated import MarketingCostsPreaggregatedTable
from posthog.hogql.database.schema.marketing_costs_precomputed import MarketingCostsPrecomputedTable
from posthog.hogql.database.schema.marketing_touchpoints_preaggregated import MarketingTouchpointsPreaggregatedTable
from posthog.hogql.database.schema.metrics import (
    MetricAttributesTable,
    MetricSamplesTable,
    MetricSeriesTable,
    MetricsKafkaMetricsTable,
    MetricsTable,
)
from posthog.hogql.database.schema.numbers import NumbersTable
from posthog.hogql.database.schema.person_distinct_id_overrides import (
    PersonDistinctIdOverridesTable,
    RawPersonDistinctIdOverridesTable,
)
from posthog.hogql.database.schema.person_distinct_ids import PersonDistinctIdsTable, RawPersonDistinctIdsTable
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable
from posthog.hogql.database.schema.persons_revenue_analytics import PersonsRevenueAnalyticsTable
from posthog.hogql.database.schema.pg_embeddings import PgEmbeddingsTable
from posthog.hogql.database.schema.preaggregation_results import PreaggregationResultsTable
from posthog.hogql.database.schema.precalculated_events import PrecalculatedEventsTable
from posthog.hogql.database.schema.precalculated_person_properties import PrecalculatedPersonPropertiesTable
from posthog.hogql.database.schema.query_log_archive import QueryLogArchiveTable, RawQueryLogArchiveTable
from posthog.hogql.database.schema.session_replay_events import RawSessionReplayEventsTable, SessionReplayEventsTable
from posthog.hogql.database.schema.session_replay_features import SessionReplayFeaturesTable
from posthog.hogql.database.schema.sessions_v1 import RawSessionsTableV1, SessionsTableV1
from posthog.hogql.database.schema.sessions_v2 import RawSessionsTableV2, SessionsTableV2
from posthog.hogql.database.schema.sessions_v3 import RawSessionsTableV3, SessionsTableV3
from posthog.hogql.database.schema.spans import TraceAttributesTable, TraceSpansTable
from posthog.hogql.database.schema.static_cohort_people import StaticCohortPeople
from posthog.hogql.database.schema.system import SystemTables
from posthog.hogql.database.schema.web_analytics_preaggregated import (
    WebPreAggregatedBouncesTable,
    WebPreAggregatedStatsTable,
)
from posthog.hogql.database.schema.web_goals_preaggregated import WebGoalsPreaggregatedTable
from posthog.hogql.database.schema.web_overview_preaggregated import WebOverviewPreaggregatedTable
from posthog.hogql.database.schema.web_stats_frustration_preaggregated import WebStatsFrustrationPreaggregatedTable
from posthog.hogql.database.schema.web_stats_paths_preaggregated import WebStatsPathsPreaggregatedTable
from posthog.hogql.database.schema.web_stats_preaggregated import WebStatsPreaggregatedTable
from posthog.hogql.database.schema.web_vitals_paths_preaggregated import WebVitalsPathsPreaggregatedTable
from posthog.hogql.database.utils import get_join_field_chain, qualify_join_key_expr
from posthog.hogql.database.warehouse_join_resolvers import data_warehouse_resolver_params
from posthog.hogql.errors import AccessDeniedError, QueryError, ResolutionError
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr
from posthog.hogql.timings import HogQLTimings

from posthog.exceptions_capture import capture_exception
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team, WeekStartDay
from posthog.ph_client import feature_enabled_or_false
from posthog.rbac.user_access_control import NO_ACCESS_LEVEL, UserAccessControl
from posthog.schema_enums import DatabaseSerializedFieldType, PersonsOnEventsMode, SessionTableVersion
from posthog.scopes import APIScopeObject
from posthog.synthetic_user import SyntheticUser

from products.data_tools.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.facade.hogql import get_warehouse_sync_warnings
from products.revenue_analytics.backend.views import RevenueAnalyticsBaseView
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    DataWarehouseTableColumns,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)

# posthog.schema (the pydantic models) is runtime-imported inside serialize()/serialize_fields()
# so it stays off django.setup(), where this module loads via the warehouse/data-modeling models.
if TYPE_CHECKING:
    from posthog.schema import (
        DatabaseSchemaDataWarehouseTable,
        DatabaseSchemaEndpointTable,
        DatabaseSchemaField,
        DatabaseSchemaManagedViewTable,
        DatabaseSchemaPostHogTable,
        DatabaseSchemaSystemTable,
        DatabaseSchemaViewTable,
        DataWarehouseSyncWarning,
        HogQLQueryModifiers,
    )

    from posthog.models import User

    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

tracer = trace.get_tracer(__name__)


@dataclasses.dataclass
class SerializedField:
    key: str
    name: str
    type: DatabaseSerializedFieldType
    schema_valid: bool
    fields: list[str] | None = None
    table: str | None = None
    chain: list[str | int] | None = None
    description: str | None = None


@dataclasses.dataclass
class HogQLDatabaseSources:
    """All I/O Database._build_from_sources needs, fetched up front by Database._fetch_sources so the
    build phase runs without any queries."""

    team: "Team"
    user: Optional["User | SyntheticUser"]
    connection_id: str | None
    modifiers: "HogQLQueryModifiers"
    is_managed_viewset_enabled: bool
    is_hogql_warehouse_access_control_enabled: bool
    # Userless internal contexts that must resolve every warehouse table/view; skips access control
    bypass_warehouse_access_control: bool
    direct_connection_metadata: dict[str, Any] | None
    # Access-control decision, computed from a warmed UserAccessControl so build does no AC queries.
    user_access_control: Optional["UserAccessControl"]
    denied_system_table_names: set[str]  # node names under the "system" node to remove during build
    group_types: list[dict[str, Any]]
    saved_queries: list["DataWarehouseSavedQuery"]
    endpoint_saved_queries: list["DataWarehouseSavedQuery"]
    revenue_views: list["RevenueAnalyticsBaseView"]
    warehouse_tables: list["DataWarehouseTable"]  # filtered to what build needs, schemas preloaded
    data_warehouse_joins: list["DataWarehouseJoin"]
    # dataWarehouseEventsModifiers path: saved query per modifier table name (None if no matching row).
    event_modifier_saved_queries: dict[str, Optional["DataWarehouseSavedQuery"]]


type DatabaseSchemaTable = (
    DatabaseSchemaPostHogTable
    | DatabaseSchemaSystemTable
    | DatabaseSchemaDataWarehouseTable
    | DatabaseSchemaViewTable
    | DatabaseSchemaManagedViewTable
    | DatabaseSchemaEndpointTable
)

logger = structlog.get_logger(__name__)


# READ BEFORE EDITING:
# --------------------
# Do NOT add any new table to this, add them to the `posthog` table node.
# This is so that we don't pollute the global namespace any further than it already is
ROOT_TABLES__DO_NOT_ADD_ANY_MORE: dict[str, TableNode] = {
    "events": TableNode(name="events", table=EventsTable()),
    "groups": TableNode(name="groups", table=GroupsTable()),
    "persons": TableNode(name="persons", table=PersonsTable()),
    "person_distinct_ids": TableNode(name="person_distinct_ids", table=PersonDistinctIdsTable()),
    "person_distinct_id_overrides": TableNode(
        name="person_distinct_id_overrides", table=PersonDistinctIdOverridesTable()
    ),
    "error_tracking_issue_fingerprint_overrides": TableNode(
        name="error_tracking_issue_fingerprint_overrides", table=ErrorTrackingIssueFingerprintOverridesTable()
    ),
    "session_replay_events": TableNode(name="session_replay_events", table=SessionReplayEventsTable()),
    "cohort_people": TableNode(name="cohort_people", table=CohortPeople()),
    "static_cohort_people": TableNode(name="static_cohort_people", table=StaticCohortPeople()),
    "cohort_membership": TableNode(name="cohort_membership", table=CohortMembershipTable()),
    "precalculated_events": TableNode(name="precalculated_events", table=PrecalculatedEventsTable()),
    "precalculated_person_properties": TableNode(
        name="precalculated_person_properties", table=PrecalculatedPersonPropertiesTable()
    ),
    "log_entries": TableNode(name="log_entries", table=LogEntriesTable()),
    "query_log": TableNode(name="query_log", table=QueryLogArchiveTable()),
    "app_metrics": TableNode(name="app_metrics", table=AppMetrics2Table()),
    "console_logs_log_entries": TableNode(name="console_logs_log_entries", table=ReplayConsoleLogsLogEntriesTable()),
    "batch_export_log_entries": TableNode(name="batch_export_log_entries", table=BatchExportLogEntriesTable()),
    "sessions": TableNode(name="sessions", table=SessionsTableV1()),
    "heatmaps": TableNode(name="heatmaps", table=HeatmapsTable()),
    "exchange_rate": TableNode(name="exchange_rate", table=ExchangeRateTable()),
    "document_embeddings": TableNode(name="document_embeddings", table=DocumentEmbeddingsTable()),
    **{name: TableNode(name=name, table=table) for name, table in HOGQL_MODEL_TABLES.items()},
    "pg_embeddings": TableNode(name="pg_embeddings", table=PgEmbeddingsTable()),
    "logs": TableNode(name="logs", table=LogsTable()),
    "log_attributes": TableNode(name="log_attributes", table=LogAttributesTable()),
    "logs_kafka_metrics": TableNode(name="logs_kafka_metrics", table=LogsKafkaMetricsTable()),
    # Web analytics pre-aggregated tables (internal use only)
    "web_pre_aggregated_stats": TableNode(name="web_pre_aggregated_stats", table=WebPreAggregatedStatsTable()),
    "web_pre_aggregated_bounces": TableNode(name="web_pre_aggregated_bounces", table=WebPreAggregatedBouncesTable()),
    "preaggregation_results": TableNode(name="preaggregation_results", table=PreaggregationResultsTable()),
    "experiment_exposures_preaggregated": TableNode(
        name="experiment_exposures_preaggregated", table=ExperimentExposuresPreaggregatedTable()
    ),
    "experiment_metric_events_preaggregated": TableNode(
        name="experiment_metric_events_preaggregated", table=ExperimentMetricEventsPreaggregatedTable()
    ),
    # Revenue analytics tables
    "persons_revenue_analytics": TableNode(name="persons_revenue_analytics", table=PersonsRevenueAnalyticsTable()),
    "groups_revenue_analytics": TableNode(name="groups_revenue_analytics", table=GroupsRevenueAnalyticsTable()),
    # Raw tables used to support the streamlined tables above
    "raw_session_replay_events": TableNode(name="raw_session_replay_events", table=RawSessionReplayEventsTable()),
    "raw_person_distinct_ids": TableNode(name="raw_person_distinct_ids", table=RawPersonDistinctIdsTable()),
    "raw_persons": TableNode(name="raw_persons", table=RawPersonsTable()),
    "raw_groups": TableNode(name="raw_groups", table=RawGroupsTable()),
    "raw_cohort_people": TableNode(name="raw_cohort_people", table=RawCohortPeople()),
    "raw_person_distinct_id_overrides": TableNode(
        name="raw_person_distinct_id_overrides", table=RawPersonDistinctIdOverridesTable()
    ),
    "raw_error_tracking_issue_fingerprint_overrides": TableNode(
        name="raw_error_tracking_issue_fingerprint_overrides",
        table=RawErrorTrackingIssueFingerprintOverridesTable(),
    ),
    "raw_error_tracking_fingerprint_issue_state": TableNode(
        name="raw_error_tracking_fingerprint_issue_state",
        table=RawErrorTrackingFingerprintIssueStateTable(),
    ),
    "raw_sessions": TableNode(name="raw_sessions", table=RawSessionsTableV1()),
    "raw_sessions_v3": TableNode(name="raw_sessions_v3", table=RawSessionsTableV3()),
    "raw_query_log": TableNode(name="raw_query_log", table=RawQueryLogArchiveTable()),
    "raw_document_embeddings": TableNode(name="raw_document_embeddings", table=RawDocumentEmbeddingsTable()),
}
# Read comment above this block before editing ^
# --------------------


# The static catalog is identical for every team/request, so build + pickle it once and reload per
# request. Each load returns an independent tree (so per-request mutation can't leak between teams);
# the in-process blob can't go stale across deploys. Every catalog node must stay picklable.
_DATABASE_ROOT_NODE_BLOBS: dict[bool, bytes] = {}
_DATABASE_ROOT_NODE_BLOBS_LOCK = threading.Lock()

# We only ever load our own freshly-built blob, but restrict the unpickler anyway as defense in depth:
# it can reconstruct only the classes the catalog is built from, so even a future change that fed it
# untrusted bytes couldn't instantiate arbitrary code (os.system, etc.). Every catalog class lives
# under posthog.hogql.* except the Workload enum and product-owned facade schema modules
# (allowlisted individually, not by prefix, to keep the surface minimal), so new table/field/AST
# types keep working and anything else fails loudly.
_CATALOG_PICKLE_MODULE_PREFIXES = ("posthog.hogql.",)
_CATALOG_PICKLE_MODULES = frozenset(
    {
        "posthog.clickhouse.workload",
        "products.customer_analytics.backend.facade.hogql",
    }
)


class _CatalogUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        if module.startswith(_CATALOG_PICKLE_MODULE_PREFIXES) or module in _CATALOG_PICKLE_MODULES:
            return super().find_class(module, name)
        # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle (allowlist guard rejecting a class, not deserialising untrusted data)
        raise pickle.UnpicklingError(f"refusing to unpickle disallowed catalog global {module}.{name}")


def build_database_root_node(*, include_posthog_tables: bool = True) -> TableNode:
    # Double-checked locking so concurrent first-callers don't each rebuild + pickle the catalog.
    blob = _DATABASE_ROOT_NODE_BLOBS.get(include_posthog_tables)
    if blob is None:
        with _DATABASE_ROOT_NODE_BLOBS_LOCK:
            blob = _DATABASE_ROOT_NODE_BLOBS.get(include_posthog_tables)
            if blob is None:
                # Built lazily, not eager-warmed at import: that would move this cost onto startup for every importer of this module, query-related or not.
                # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle (serialising our own code-built catalog; loads are restricted by _CatalogUnpickler)
                blob = pickle.dumps(
                    _construct_database_root_node(include_posthog_tables=include_posthog_tables),
                    protocol=pickle.HIGHEST_PROTOCOL,
                )
                blob = pickletools.optimize(blob)  # drop unused memo opcodes: ~10% smaller, faster load
                _DATABASE_ROOT_NODE_BLOBS[include_posthog_tables] = blob
    # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle (_CatalogUnpickler restricts find_class to catalog classes, so untrusted bytes still can't execute code)
    return _CatalogUnpickler(io.BytesIO(blob)).load()


def _construct_database_root_node(*, include_posthog_tables: bool) -> TableNode:
    def clone_root_tables() -> dict[str, TableNode]:
        return {name: table_node.model_copy(deep=True) for name, table_node in ROOT_TABLES__DO_NOT_ADD_ANY_MORE.items()}

    children: dict[str, TableNode] = {
        "numbers": TableNode(name="numbers", table=NumbersTable()),
        "range": TableNode(name="range", table=RangeTable()),
        "generate_series": TableNode(name="generate_series", table=GenerateSeriesTable()),
    }

    if include_posthog_tables:
        root_tables = clone_root_tables()
        children = {
            **root_tables,
            "posthog": TableNode(
                name="posthog",
                children={
                    **clone_root_tables(),
                    # Add new tables here
                    "ai_events": TableNode(name="ai_events", table=AiEventsTable()),
                    "trace_spans": TableNode(name="trace_spans", table=TraceSpansTable()),
                    "trace_attributes": TableNode(name="trace_attributes", table=TraceAttributesTable()),
                    "session_replay_features": TableNode(
                        name="session_replay_features", table=SessionReplayFeaturesTable()
                    ),
                    "hog_invocation_results": TableNode(
                        name="hog_invocation_results", table=HogInvocationResultsTable()
                    ),
                    "metrics": TableNode(name="metrics", table=MetricsTable()),
                    "metric_samples": TableNode(name="metric_samples", table=MetricSamplesTable()),
                    "metric_series": TableNode(name="metric_series", table=MetricSeriesTable()),
                    "metric_attributes": TableNode(name="metric_attributes", table=MetricAttributesTable()),
                    "metrics_kafka_metrics": TableNode(name="metrics_kafka_metrics", table=MetricsKafkaMetricsTable()),
                    "error_tracking_fingerprint_issue_state": TableNode(
                        name="error_tracking_fingerprint_issue_state",
                        table=ErrorTrackingFingerprintIssueStateTable(),
                    ),
                    "web_overview_preaggregated": TableNode(
                        name="web_overview_preaggregated", table=WebOverviewPreaggregatedTable()
                    ),
                    "marketing_touchpoints_preaggregated": TableNode(
                        name="marketing_touchpoints_preaggregated",
                        table=MarketingTouchpointsPreaggregatedTable(),
                    ),
                    "marketing_conversions_preaggregated": TableNode(
                        name="marketing_conversions_preaggregated",
                        table=MarketingConversionsPreaggregatedTable(),
                    ),
                    "marketing_costs_preaggregated": TableNode(
                        name="marketing_costs_preaggregated",
                        table=MarketingCostsPreaggregatedTable(),
                    ),
                    "web_stats_paths_preaggregated": TableNode(
                        name="web_stats_paths_preaggregated", table=WebStatsPathsPreaggregatedTable()
                    ),
                    "web_stats_preaggregated": TableNode(
                        name="web_stats_preaggregated", table=WebStatsPreaggregatedTable()
                    ),
                    "web_vitals_paths_preaggregated": TableNode(
                        name="web_vitals_paths_preaggregated", table=WebVitalsPathsPreaggregatedTable()
                    ),
                    "web_stats_frustration_preaggregated": TableNode(
                        name="web_stats_frustration_preaggregated", table=WebStatsFrustrationPreaggregatedTable()
                    ),
                    "web_goals_preaggregated": TableNode(
                        name="web_goals_preaggregated", table=WebGoalsPreaggregatedTable()
                    ),
                },
            ),
            "system": SystemTables(),
            # Deduplicated read interface over posthog.marketing_costs_preaggregated. Registered at root
            # (like `sessions`) because a lazy/aggregating view only resolves cleanly from the root scope.
            "marketing_costs_precomputed": TableNode(
                name="marketing_costs_precomputed", table=MarketingCostsPrecomputedTable()
            ),
            **children,
        }

    return TableNode(children=children)


@cache
def _system_table_access_scopes() -> tuple[tuple[str, APIScopeObject], ...]:
    """(table name, access scope) for the access-controlled Postgres system tables.

    Cached for the process lifetime — this result directly gates table visibility in access-control
    decisions, so every entry here MUST remain process-static. Do NOT make a system table's
    access_scope dynamic (per-team, per-flag, or env-driven at call time): this cache would silently
    serve stale scopes and bypass the restriction. Today SystemTables().children is a static
    class-level dict of module-level PostgresTable constants, which satisfies that invariant.
    """
    return tuple(
        (name, table_node.table.access_scope)
        for name, table_node in SystemTables().children.items()
        if isinstance(table_node.table, PostgresTable) and table_node.table.access_scope is not None
    )


def _compute_system_table_access_decision(
    team: "Team",
    user: Optional["User | SyntheticUser"],
    user_access_control: Optional["UserAccessControl"] = None,
) -> tuple[Optional["UserAccessControl"], set[str]]:
    """Decide which scoped system tables to hide, doing the access-control I/O here so the build phase
    can apply the result without querying. Returns the warmed UserAccessControl (preloaded, so later
    reads are query-free) and the system-node table names to remove.

    Pass user_access_control when it's already preloaded to reuse the instance and avoid an extra query."""
    scoped_tables = _system_table_access_scopes()

    # Anonymous or synthetic principal: keep only access-controlled tables its scopes cover (none for anonymous / team token).
    if user is None or isinstance(user, SyntheticUser):
        readable_scopes = user.readable_system_table_access_scopes() if user is not None else set()
        return None, {name for name, access_scope in scoped_tables if access_scope not in readable_scopes}

    user_access_control = user_access_control or UserAccessControl(user=user, team=team)

    org_membership = user_access_control._organization_membership
    if org_membership and org_membership.level >= OrganizationMembership.Level.ADMIN:
        return user_access_control, set()

    denied: set[str] = set()
    for name, access_scope in scoped_tables:
        access_level = user_access_control.access_level_for_resource(access_scope)
        if access_level and access_level != NO_ACCESS_LEVEL:
            continue  # User has access, keep it
        denied.add(name)

    return user_access_control, denied


class Database(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Users can query from the tables below
    tables: TableNode

    _warehouse_table_names: list[str] = []
    _warehouse_self_managed_table_names: list[str] = []
    _view_table_names: list[str] = []
    _denied_tables: set[str] = set()  # Tables user doesn't have permission to access
    _connection_id: str | None = None
    _direct_connection_metadata: dict[str, Any] | None = None
    _direct_access_warehouse_table_names: set[str] = set()
    # Warnings about data warehouse tables (failed/paused/billing-limited/stale syncs),
    # keyed by HogQL DataWarehouseTable.table_id (str(Django table UUID)).
    _data_warehouse_sync_warnings: dict[str, list["DataWarehouseSyncWarning"]] = {}

    _timezone: str | None
    _week_start_day: WeekStartDay | None

    def __init__(
        self,
        timezone: str | None = None,
        week_start_day: WeekStartDay | None = None,
        include_posthog_tables: bool = True,
    ):
        super().__init__(tables=build_database_root_node(include_posthog_tables=include_posthog_tables))
        try:
            self._timezone = str(ZoneInfo(timezone)) if timezone else None
        except ZoneInfoNotFoundError:
            raise ValueError(f"Unknown timezone: '{str(timezone)}'")

        self._week_start_day = week_start_day
        self._warehouse_table_names = []
        self._warehouse_self_managed_table_names = []
        self._view_table_names = []
        self._denied_tables = set()
        self._connection_id = None
        self._direct_connection_metadata = None
        self._direct_access_warehouse_table_names = set()
        self._data_warehouse_sync_warnings = {}
        self._serialization_errors: dict[str, str] = {}  # table_key -> error_message
        self.user_access_control: Optional[UserAccessControl] = None

    def get_timezone(self) -> str:
        return self._timezone or "UTC"

    def get_week_start_day(self) -> WeekStartDay:
        return self._week_start_day or WeekStartDay.SUNDAY

    def get_serialization_errors(self) -> dict[str, str]:
        """Return any errors encountered during serialization."""
        return self._serialization_errors.copy()

    def has_table(self, table_name: str | list[str]) -> bool:
        if isinstance(table_name, str):
            table_name = table_name.split(".")
        return self.tables.has_child(table_name)

    def is_table_access_denied(self, table_name: str | list[str]) -> bool:
        """True if access control denied this table when the HogQL database was built,
        so callers can surface an access denied error instead of unknown table"""
        if isinstance(table_name, list):
            table_name = ".".join(str(part) for part in table_name)
        return table_name in self._denied_tables

    def get_table_node(self, table_name: str | list[str]) -> TableNode:
        if isinstance(table_name, str):
            table_name = table_name.split(".")

        if isinstance(table_name, list) and len(table_name) == 1 and "." in table_name[0]:
            table_name = table_name[0].split(".")

        return self.tables.get_child(table_name)

    def get_table(self, table_name: str | list[str]) -> Table:
        try:
            return cast(Table, self.get_table_node(table_name).get())
        except ResolutionError as e:
            if isinstance(table_name, list):
                table_name = ".".join(table_name)
            if table_name in self._denied_tables:
                raise AccessDeniedError(f"You don't have access to table `{table_name}`.") from e
            suggestions = self._suggest_table_names(table_name)
            suffix = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
            raise QueryError(f"Unknown table `{table_name}`.{suffix}") from e

    def _suggest_table_names(self, name: str, *, limit: int = 3) -> list[str]:
        """Return up to `limit` close matches for a mistyped table name.

        Uses a relatively strict cutoff so common exact-text assertions on
        'Unknown table `...`.' stay stable when the mistyped name has no
        realistic neighbor in the catalog.

        Builds the candidate list from the raw name caches rather than from
        `get_all_table_names()` — the latter verifies each warehouse entry by
        calling `get_table()`, which would recurse back into this helper when
        a warehouse table fails to resolve.
        """
        import difflib

        try:
            candidates = set(self.get_posthog_table_names())
            candidates.update(self._warehouse_table_names)
            candidates.update(self._warehouse_self_managed_table_names)
            candidates.update(self._view_table_names)
        except Exception:
            return []
        # Drop any candidate that matches the input — suggesting `persons` for `persons`
        # is noise, and on a direct connection the same name can exist in the broader
        # catalog without being available on the source we actually queried.
        lowered = name.casefold()
        candidates = {c for c in candidates if c.casefold() != lowered}
        if not candidates:
            return []
        return difflib.get_close_matches(name, sorted(candidates), n=limit, cutoff=0.7)

    def get_all_table_names(self) -> list[str]:
        warehouse_table_names: list[str] = []
        for table_name in self._warehouse_table_names:
            try:
                table = self.get_table(table_name)
            except QueryError:
                continue

            if table.name == table_name:
                warehouse_table_names.append(table_name)

        if self._is_direct_query():
            return sorted(set(warehouse_table_names))

        return (
            self.get_posthog_table_names()
            + sorted(set(warehouse_table_names))
            + self._warehouse_self_managed_table_names
            + self._view_table_names
        )

    # These are the tables exposed via SQL editor autocomplete and data management
    def get_posthog_table_names(self, include_hidden: bool = False) -> list[str]:
        if include_hidden:
            root_keys = set(ROOT_TABLES__DO_NOT_ADD_ANY_MORE.keys())
            posthog_node = self.tables.children.get("posthog")
            if posthog_node and posthog_node.children:
                posthog_only_keys = {f"posthog.{k}" for k in posthog_node.children.keys() if k not in root_keys}
            else:
                posthog_only_keys = set()
            return sorted(root_keys | posthog_only_keys)

        return [
            "events",
            "groups",
            "persons",
            "sessions",
            "logs",
            *self.get_system_table_names(),
        ]

    def get_system_table_names(self) -> list[str]:
        system_tables = self.tables.children.get("system")
        if not isinstance(system_tables, SystemTables):
            return []

        return ["query_log", *system_tables.resolve_visible_table_names()]

    def get_warehouse_table_names(self) -> list[str]:
        return self._warehouse_table_names + self._warehouse_self_managed_table_names

    def get_view_names(self) -> list[str]:
        return self._view_table_names

    def _add_warehouse_tables(self, node: TableNode):
        self.tables.merge_with(node, table_conflict_mode="override" if self._is_direct_query() else "ignore")
        for name in sorted(node.resolve_all_table_names()):
            self._warehouse_table_names.append(name)

    def _add_warehouse_self_managed_tables(self, node: TableNode):
        self.tables.merge_with(node)
        for name in sorted(node.resolve_all_table_names()):
            self._warehouse_self_managed_table_names.append(name)

    def _add_views(self, node: TableNode):
        self.tables.merge_with(node)
        for name in sorted(node.resolve_all_table_names()):
            self._view_table_names.append(name)

    def _is_direct_query(self) -> bool:
        return self._connection_id is not None

    @staticmethod
    def _is_helper_function_table(table: object) -> bool:
        return isinstance(table, FunctionCallTable) and not isinstance(table, (DirectSQLTable, PostgresTable, S3Table))

    def _remove_lazy_joins_to_disallowed_tables(self, allowed_table_names: set[str]) -> None:
        def should_keep_join(field: LazyJoin) -> bool:
            join_table = field.join_table

            if isinstance(join_table, str):
                return join_table in allowed_table_names

            if self._is_helper_function_table(join_table):
                return True

            if not isinstance(join_table.name, str):
                return True

            return join_table.name in allowed_table_names

        def visit(node: TableNode) -> None:
            table = node.table
            if isinstance(table, Table):
                for field_name, field in list(table.fields.items()):
                    if isinstance(field, LazyJoin) and not should_keep_join(field):
                        del table.fields[field_name]

            for child in node.children.values():
                visit(child)

        visit(self.tables)

    def prune_to_table_names(self, allowed_table_names: set[str]) -> None:
        def prune_node(node: TableNode, chain: list[str]) -> bool:
            full_name = ".".join(chain)
            keep_table = node.table is not None and (
                full_name in allowed_table_names or (len(chain) > 0 and self._is_helper_function_table(node.table))
            )

            pruned_children: dict[str, TableNode] = {}
            for child_name, child in node.children.items():
                if prune_node(child, [*chain, child_name]):
                    pruned_children[child_name] = child
            node.children = pruned_children

            return node.name == "root" or keep_table or len(node.children) > 0

        prune_node(self.tables, [])
        self._warehouse_table_names = [name for name in self._warehouse_table_names if name in allowed_table_names]
        self._warehouse_self_managed_table_names = [
            name for name in self._warehouse_self_managed_table_names if name in allowed_table_names
        ]
        self._view_table_names = [name for name in self._view_table_names if name in allowed_table_names]
        self._remove_lazy_joins_to_disallowed_tables(allowed_table_names)

    def apply_schema_scope(self) -> None:
        if self._is_direct_query():
            self.prune_to_table_names(set(self._warehouse_table_names))
            return

        allowed_table_names = set(self.tables.resolve_all_table_names())
        built_in_global_table_names = set(self.get_posthog_table_names(include_hidden=True))
        built_in_global_table_names.update(self.get_system_table_names())
        built_in_global_table_names.add("numbers")

        # Direct connections stay hidden from the default scope, but they must not evict
        # built-in PostHog tables when a direct source reuses names like `events` or `persons`.
        hidden_direct_name_collisions = self._direct_access_warehouse_table_names & built_in_global_table_names
        direct_table_names_to_hide = self._direct_access_warehouse_table_names - built_in_global_table_names
        allowed_table_names.difference_update(direct_table_names_to_hide)
        self.prune_to_table_names(allowed_table_names)
        self._warehouse_table_names = [
            name for name in self._warehouse_table_names if name not in hidden_direct_name_collisions
        ]

    def _apply_system_table_access(
        self, user_access_control: Optional["UserAccessControl"], denied_system_table_names: set[str]
    ) -> None:
        """Apply the precomputed access-control decision from _compute_system_table_access_decision,
        without querying."""
        if user_access_control is not None:
            self.user_access_control = user_access_control

        # Record only denials we actually applied, so a database with no "system" node denies nothing.
        removed: set[str] = set()
        if denied_system_table_names:
            system_node = self.tables.children.get("system")
            if system_node is not None and hasattr(system_node, "children"):
                for name in denied_system_table_names:
                    if name in system_node.children:
                        del system_node.children[name]
                        removed.add(name)

        self._denied_tables = {f"system.{name}" for name in removed}

    def _is_warehouse_table_denied(self, table: "DataWarehouseTable") -> bool:
        """
        Returns True if the user can't query this warehouse table.
        Userless context (no UserAccessControl) fails closed - every table is denied.
        """
        uac = self.user_access_control
        if uac is not None and (
            uac.is_organization_admin or uac.check_access_level_for_object(table, required_level="viewer")
        ):
            return False

        # Add table names to denied tables so the query raises "You don't have access" instead of "Unknown table"
        self._denied_tables.add(table.name)
        if table.external_data_source:
            for table_key in _get_warehouse_table_keys(table, direct_query=self._is_direct_query()):
                self._denied_tables.add(table_key)
        return True

    def _is_warehouse_view_denied(self, saved_query: Any) -> bool:
        """
        View counterpart of `_is_warehouse_table_denied`.
        Closes the gap where a user denied access to a warehouse table could otherwise SELECT
        through a non-materialized view that references it.
        Userless context (no UserAccessControl) fails closed - every view is denied.
        """
        uac = self.user_access_control
        if uac is not None and (
            uac.is_organization_admin or uac.check_access_level_for_object(saved_query, required_level="viewer")
        ):
            return False

        # Add view names to denied tables so the query raises "You don't have access" instead of "Unknown table"
        self._denied_tables.add(saved_query.name)
        return True

    def serialize(
        self,
        context: HogQLContext,
        include_only: set[str] | None = None,
        include_hidden_posthog_tables: bool = False,
    ) -> dict[str, DatabaseSchemaTable]:
        from posthog.schema import (  # noqa: PLC0415
            DatabaseSchemaDataWarehouseTable,
            DatabaseSchemaEndpointTable,
            DatabaseSchemaManagedViewTable,
            DatabaseSchemaPostHogTable,
            DatabaseSchemaSchema,
            DatabaseSchemaSource,
            DatabaseSchemaSystemTable,
            DatabaseSchemaViewTable,
            HogQLQuery,
        )

        from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

        tables: dict[str, DatabaseSchemaTable] = {}

        if context.team_id is None:
            raise ResolutionError("Must provide team_id to serialize database")

        # PostHog tables
        posthog_table_names = (
            []
            if self._is_direct_query()
            else self.get_posthog_table_names(include_hidden=include_hidden_posthog_tables)
        )
        for table_name in posthog_table_names:
            if include_only and table_name not in include_only:
                continue

            field_input: dict[str, Any] = {}
            table = self.get_table(table_name)
            if isinstance(table, Table):
                field_input = _schema_field_input(table)

            fields = serialize_fields(field_input, context, table_name.split("."), table_type="posthog")
            fields_dict = {field.name: field for field in fields}
            tables[table_name] = DatabaseSchemaPostHogTable(fields=fields_dict, id=table_name, name=table_name)

        # System tables
        system_tables = [] if self._is_direct_query() else self.get_system_table_names()
        for table_key in system_tables:
            if include_only and table_key not in include_only:
                continue

            system_field_input: dict[str, Any] = {}
            table = self.get_table(table_key)
            if isinstance(table, Table):
                system_field_input = _schema_field_input(table)

            fields = serialize_fields(system_field_input, context, table_key.split("."), table_type="posthog")
            fields_dict = {field.name: field for field in fields}
            tables[table_key] = DatabaseSchemaSystemTable(fields=fields_dict, id=table_key, name=table_key)

        # Data Warehouse Tables and Views - Fetch all related data in one go
        warehouse_table_names = self.get_warehouse_table_names()
        views = [] if self._is_direct_query() else self.get_view_names()

        warehouse_tables_query = (
            DataWarehouseTable.raw_objects.select_related("credential", "external_data_source")
            .prefetch_related(
                Prefetch(
                    "external_data_source__jobs",
                    queryset=ExternalDataJob.objects.filter(status="Completed", team_id=context.team_id).order_by(
                        "-created_at"
                    )[:1],
                    to_attr="latest_completed_job",
                ),
            )
            # `queryable()` drops soft-deleted tables and orphans of a soft-deleted source, so an
            # orphan can't shadow the live table sharing its name in the SQL editor catalog.
            .queryable()
            .filter(team_id=context.team_id)
            # The catalog is built last-write-wins per table key, so order created_at ascending to
            # land the newest row last when two live tables share a name — matching tree resolution.
            .order_by("external_data_source__prefix", "external_data_source__source_type", "name", "created_at")
        )
        if self._is_direct_query():
            warehouse_tables_query = warehouse_tables_query.filter(external_data_source_id=self._connection_id)
        elif warehouse_table_names:
            warehouse_tables_query = warehouse_tables_query.filter(name__in=warehouse_table_names)
        else:
            warehouse_tables_query = warehouse_tables_query.none()

        warehouse_tables_with_data = list(warehouse_tables_query.all())
        _preload_active_external_data_schemas(warehouse_tables_with_data)
        if self._is_direct_query():
            warehouse_tables_with_data = [
                warehouse_table
                for warehouse_table in warehouse_tables_with_data
                if _should_include_connection_table(
                    warehouse_table,
                    connection_id=cast(str, self._connection_id),
                )
            ]
        allowed_warehouse_table_names = set(warehouse_table_names) if self._is_direct_query() else None

        # Process warehouse tables
        for warehouse_table in warehouse_tables_with_data:
            # Get schema from prefetched data
            schema_data = _get_active_external_data_schemas(warehouse_table)
            if not schema_data:
                schema = None
            else:
                db_schema = schema_data[0]
                schema = DatabaseSchemaSchema(
                    id=str(db_schema.id),
                    name=db_schema.name,
                    should_sync=db_schema.should_sync,
                    incremental=db_schema.is_incremental or db_schema.is_webhook,
                    status=db_schema.status,
                    last_synced_at=str(db_schema.last_synced_at),
                )

            # Get source from prefetched data
            if warehouse_table.external_data_source is None:
                source = None
            else:
                db_source = warehouse_table.external_data_source
                latest_completed_run = (
                    db_source.latest_completed_job[0]
                    if hasattr(db_source, "latest_completed_job") and db_source.latest_completed_job
                    else None
                )
                source = DatabaseSchemaSource(
                    id=str(db_source.id),
                    status=db_source.status,
                    source_type=db_source.source_type,
                    access_method=db_source.access_method,
                    prefix=db_source.prefix or "",
                    last_synced_at=str(latest_completed_run.created_at) if latest_completed_run else None,
                )

            for table_key in _get_warehouse_table_keys(warehouse_table, direct_query=self._is_direct_query()):
                if allowed_warehouse_table_names is not None and table_key not in allowed_warehouse_table_names:
                    continue

                # Warehouse tables are queryable by their dotted key (`zendesk.groups`) or their raw
                # underscore name (`zendesk_groups`); honor either form in `include_only`.
                if include_only and table_key not in include_only and warehouse_table.name not in include_only:
                    continue

                try:
                    field_input = {}
                    table = self.get_table(table_key)
                    if isinstance(table, Table):
                        field_input = table.fields

                    fields = serialize_fields(
                        field_input, context, table_key.split("."), warehouse_table.columns, table_type="external"
                    )
                    fields_dict = {field.name: field for field in fields}

                    # The table is also queryable by its raw underscore name, which is registered
                    # separately from the dotted `table_key`. Surface it so search matches either form.
                    search_aliases = [warehouse_table.name] if warehouse_table.name != table_key else None

                    tables[table_key] = DatabaseSchemaDataWarehouseTable(
                        fields=fields_dict,
                        id=str(warehouse_table.id),
                        name=table_key,
                        search_aliases=search_aliases,
                        format=warehouse_table.format,
                        url_pattern=warehouse_table.url_pattern,
                        schema=schema,
                        source=source,
                        row_count=warehouse_table.row_count,
                    )
                except (QueryError, ResolutionError) as e:
                    logger.warning(
                        f"Failed to serialize data warehouse table '{table_key}': {str(e)}",
                        exc_info=True,
                    )
                    self._serialization_errors[table_key] = str(e)
                    continue

        # Fetch all views in a single query
        all_views = (
            DataWarehouseSavedQuery.objects.select_related("table")
            .exclude(deleted=True)
            .filter(team_id=context.team_id)
            .all()
            if views
            else []
        )

        # Process views using prefetched data
        views_dict = {view.name: view for view in all_views}
        for view_name in views:
            if include_only and view_name not in include_only:
                continue

            try:
                view = self.get_table(view_name)
            except QueryError:
                continue

            fields = serialize_fields(view.fields, context, view_name.split("."), table_type="external")
            fields_dict = {field.name: field for field in fields}

            if isinstance(view, RevenueAnalyticsBaseView):
                tables[view_name] = DatabaseSchemaManagedViewTable(
                    fields=fields_dict,
                    id=view.name,  # We don't have a UUID for revenue views because they're not saved, just reuse the name
                    name=view.name,
                    kind=view.DATABASE_SCHEMA_TABLE_KIND,
                    source_id=view.source_id,
                    query=HogQLQuery(query=view.query),
                )

                continue

            saved_query = views_dict.get(view_name)

            if not saved_query:
                continue

            row_count: int | None = None
            if saved_query.table:
                row_count = saved_query.table.row_count

            if saved_query and saved_query.origin == DataWarehouseSavedQuery.Origin.ENDPOINT:
                tables[view_name] = DatabaseSchemaEndpointTable(
                    fields=fields_dict,
                    id=str(saved_query.pk),
                    name=view_name,
                    query=HogQLQuery(query=saved_query.query["query"]),  # type: ignore[index]
                    row_count=row_count,
                    status=saved_query.status,
                )
                continue

            tables[view_name] = DatabaseSchemaViewTable(
                fields=fields_dict,
                id=str(saved_query.pk),
                name=view_name,
                query=HogQLQuery(query=saved_query.query["query"]),  # type: ignore[index]
                row_count=row_count,
            )

        return tables

    @staticmethod
    @tracer.start_as_current_span("create_hogql_database")  # Legacy name to keep backwards compatibility
    def create_for(
        team_id: int | None = None,
        *,
        team: Optional["Team"] = None,
        user: Optional["User | SyntheticUser"] = None,
        user_access_control: Optional["UserAccessControl"] = None,
        modifiers: "HogQLQueryModifiers | None" = None,
        timings: HogQLTimings | None = None,
        connection_id: str | None = None,
        bypass_warehouse_access_control: bool = False,
        build_postgres_foreign_keys: bool = True,
    ) -> "Database":
        if timings is None:
            timings = HogQLTimings()

        sources = Database._fetch_sources(
            team_id,
            team=team,
            user=user,
            user_access_control=user_access_control,
            modifiers=modifiers,
            timings=timings,
            connection_id=connection_id,
            bypass_warehouse_access_control=bypass_warehouse_access_control,
        )
        return Database._build_from_sources(
            sources, timings=timings, build_postgres_foreign_keys=build_postgres_foreign_keys
        )

    @staticmethod
    def _fetch_sources(
        team_id: int | None = None,
        *,
        team: Optional["Team"] = None,
        user: Optional["User | SyntheticUser"] = None,
        user_access_control: Optional["UserAccessControl"] = None,
        modifiers: "HogQLQueryModifiers | None" = None,
        timings: HogQLTimings | None = None,
        connection_id: str | None = None,
        bypass_warehouse_access_control: bool = False,
    ) -> HogQLDatabaseSources:
        """Run every Postgres query / feature-flag check / external request needed to build the
        database, returning a bundle that Database._build_from_sources turns into tables with no I/O."""
        if timings is None:
            timings = HogQLTimings()

        db_span = trace.get_current_span()

        from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

        with timings.measure("team", emit_span=True):
            if team_id is None and team is None:
                raise ValueError("Either team_id or team must be provided")

            if team is not None and team_id is not None and team.pk != team_id:
                raise ValueError("team_id and team must be the same")

            if team is None:
                try:
                    team = Team.objects.get(pk=team_id)
                except Team.DoesNotExist:
                    raise QueryError(f"Team with id {team_id} does not exist") from None

            # Team is definitely not None at this point, make mypy believe that
            team = cast("Team", team)

            db_span.set_attribute("team_id", team.pk)

        is_direct_query = connection_id is not None

        with timings.measure("feature_flags", emit_span=True):
            is_managed_viewset_enabled = feature_enabled_or_false(
                "managed-viewsets",
                str(team.uuid),
                groups={
                    "organization": str(team.organization_id),
                    "project": str(team.id),
                },
                group_properties={
                    "organization": {
                        "id": str(team.organization_id),
                    },
                    "project": {
                        "id": str(team.id),
                    },
                },
                send_feature_flag_events=False,
            )

        with timings.measure("database", emit_span=True):
            direct_connection_metadata: dict[str, Any] | None = None
            if connection_id is not None:
                direct_source = (
                    ExternalDataSource.objects.filter(
                        team_id=team.pk,
                        id=connection_id,
                        access_method=ExternalDataSource.AccessMethod.DIRECT,
                    )
                    .select_related(None)
                    .only("connection_metadata")
                    .first()
                )
                if direct_source is not None:
                    direct_connection_metadata = direct_source.connection_metadata

        with timings.measure("filter_system_tables_for_user", emit_span=True):
            # System-table access control always applies; Only warehouse table/view support bypass.
            # Pass the caller's user_access_control through: when already preloaded it's reused, so the
            # bulk access-control fetch happens once per run instead of once per database build.
            user_access_control, denied_system_table_names = _compute_system_table_access_decision(
                team, user, user_access_control
            )

        is_hogql_warehouse_access_control_enabled = feature_enabled_or_false(
            "hogql-warehouse-access-control",
            str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            send_feature_flag_events=False,
        )

        with timings.measure("modifiers", emit_span=True):
            modifiers = create_default_modifiers_for_team(team, modifiers)

        with timings.measure("group_type_mapping", emit_span=True):
            group_types: list[dict[str, Any]] = (
                [] if is_direct_query else list(get_group_types_for_project(team.project_id))
            )

        with timings.measure("data_warehouse_saved_query", emit_span=True):
            saved_queries: list[DataWarehouseSavedQuery] = []
            # Direct-connection queries do not expose saved queries.
            if not is_direct_query:
                with timings.measure("select"):
                    queryset = (
                        DataWarehouseSavedQuery.objects.filter(team_id=team.pk)
                        .exclude(deleted=True)
                        .order_by("name")
                        # created_by for the access-control creator check
                        .select_related("table", "managed_viewset", "created_by")
                        # credential attached in bulk below, not joined per row
                    )
                    if not is_managed_viewset_enabled:
                        queryset = queryset.filter(managed_viewset__isnull=True)
                    saved_queries = list(queryset)

        with timings.measure("endpoint_saved_query", emit_span=True):
            endpoint_saved_queries: list[DataWarehouseSavedQuery] = []
            if not is_direct_query:
                try:
                    endpoint_saved_queries = list(
                        DataWarehouseSavedQuery.objects.filter(team_id=team.pk)
                        .filter(origin=DataWarehouseSavedQuery.Origin.ENDPOINT)
                        .exclude(deleted=True)
                        # created_by for the access-control creator check
                        .select_related("table", "created_by")
                        # credential attached in bulk below, not joined per row
                    )
                except Exception as e:
                    capture_exception(e)

        with timings.measure("revenue_analytics_views", emit_span=True):
            revenue_views: list[RevenueAnalyticsBaseView] = []
            if not is_direct_query:
                try:
                    if not is_managed_viewset_enabled:
                        from products.revenue_analytics.backend.views.orchestrator import (  # noqa: PLC0415
                            build_all_revenue_analytics_views,
                        )

                        revenue_views = list(build_all_revenue_analytics_views(team, timings))
                except Exception as e:
                    capture_exception(e)

        # Materialized views store their backing table under the saved-query-specific S3 path.
        # Exclude that private storage table so the view owns access control, even after a rename.
        backing_table_ids = {
            sq.table_id
            for sq in (*saved_queries, *endpoint_saved_queries)
            if sq.table_id is not None and sq.table is not None and sq.folder_path in sq.table.url_pattern
        }

        with timings.measure("data_warehouse_tables", emit_span=True):
            with timings.measure("select", emit_span=True):
                tables_query = (
                    # `queryable()` drops soft-deleted tables and orphans left by a soft-deleted
                    # source, so an orphan can't shadow the live table sharing its name.
                    DataWarehouseTable.raw_objects.filter(team_id=team.pk)
                    .queryable()
                    # created_by is hydrated for the warehouse access-control creator check
                    .select_related("created_by")
                    # credential/external_data_source attached in bulk below, not joined per row; the
                    # access_method filter still joins the source for its WHERE without hydrating it.
                    # Deterministic tiebreak when two live tables share a name: newest wins, since
                    # name collisions resolve first-come-first-served when added to the table tree.
                    .order_by("-created_at")
                )
                if backing_table_ids:
                    tables_query = tables_query.exclude(id__in=backing_table_ids)
                if is_direct_query:
                    tables_query = tables_query.filter(external_data_source_id=connection_id)
                else:
                    tables_query = tables_query.exclude(
                        external_data_source__access_method=ExternalDataSource.AccessMethod.DIRECT
                    )

                warehouse_tables: list[DataWarehouseTable] = list(tables_query)
                # Direct-query mode builds the direct-postgres tables, which read source.job_inputs, so
                # keep it hydrated there instead of lazily reloading it per table.
                _attach_external_data_sources(warehouse_tables, team_id=team.pk, defer_job_inputs=not is_direct_query)
                _preload_active_external_data_schemas(warehouse_tables)
                if is_direct_query:
                    warehouse_tables = [
                        table
                        for table in warehouse_tables
                        if _should_include_connection_table(
                            table,
                            connection_id=cast(str, connection_id),
                        )
                    ]

        with timings.measure("data_warehouse_joins", emit_span=True):
            data_warehouse_joins = list(DataWarehouseJoin.objects.filter(team_id=team.pk).exclude(deleted=True))

        with timings.measure("attach_credentials", emit_span=True):
            # Tables and view-backing tables share the credential pool; attach across all of them.
            credentialed_tables: list[DataWarehouseTable] = [*warehouse_tables]
            credentialed_tables.extend(
                sq.table for sq in saved_queries if sq.table_id is not None and sq.table is not None
            )
            credentialed_tables.extend(
                sq.table for sq in endpoint_saved_queries if sq.table_id is not None and sq.table is not None
            )
            _attach_decrypted_credentials(credentialed_tables, team_id=team.pk)

        # Prefetch the saved query each modifier may resolve against; the table models come from the
        # warehouse_tables fetch.
        event_modifier_saved_queries: dict[str, Optional[DataWarehouseSavedQuery]] = {}
        if modifiers.dataWarehouseEventsModifiers:
            with timings.measure("data_warehouse_event_modifiers_fetch", emit_span=True):
                for warehouse_modifier in modifiers.dataWarehouseEventsModifiers:
                    name = warehouse_modifier.table_name
                    if name in event_modifier_saved_queries:
                        continue
                    try:
                        event_modifier_saved_queries[name] = (
                            DataWarehouseSavedQuery.objects.exclude(deleted=True)
                            .filter(team_id=team.pk, name=name)
                            .latest("created_at")
                        )
                    except DataWarehouseSavedQuery.DoesNotExist:
                        event_modifier_saved_queries[name] = None

        return HogQLDatabaseSources(
            team=team,
            user=user,
            connection_id=connection_id,
            modifiers=modifiers,
            is_managed_viewset_enabled=is_managed_viewset_enabled,
            is_hogql_warehouse_access_control_enabled=is_hogql_warehouse_access_control_enabled,
            # Synthetic principals (project secret API keys) are project-wide and bypass object-level
            # RBAC by design, so they bypass warehouse access control too. System tables stay
            # scope-gated for them via _compute_system_table_access_decision above. This field only
            # gates the warehouse checks in _build_from_sources.
            bypass_warehouse_access_control=bypass_warehouse_access_control or isinstance(user, SyntheticUser),
            direct_connection_metadata=direct_connection_metadata,
            user_access_control=user_access_control,
            denied_system_table_names=denied_system_table_names,
            group_types=group_types,
            saved_queries=saved_queries,
            endpoint_saved_queries=endpoint_saved_queries,
            revenue_views=revenue_views,
            warehouse_tables=warehouse_tables,
            data_warehouse_joins=data_warehouse_joins,
            event_modifier_saved_queries=event_modifier_saved_queries,
        )

    @staticmethod
    def _build_from_sources(
        sources: HogQLDatabaseSources,
        timings: HogQLTimings | None = None,
        build_postgres_foreign_keys: bool = True,
    ) -> "Database":
        """Construct the HogQL Database purely from already-fetched sources. Performs no I/O: every
        Postgres query and feature-flag check was done up front in Database._fetch_sources."""
        if timings is None:
            timings = HogQLTimings()

        db_span = trace.get_current_span()

        from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

        team = sources.team
        team_id = team.pk
        modifiers = sources.modifiers

        with timings.measure("database", emit_span=True):
            database = Database(
                timezone=team.timezone,
                week_start_day=team.week_start_day,
                include_posthog_tables=sources.connection_id is None,
            )
            if sources.connection_id is not None:
                database._connection_id = sources.connection_id
                if sources.direct_connection_metadata is not None:
                    database._direct_connection_metadata = sources.direct_connection_metadata

        with timings.measure("filter_system_tables_for_user", emit_span=True):
            database._apply_system_table_access(sources.user_access_control, sources.denied_system_table_names)

        with timings.measure("modifiers", emit_span=True):
            if not database._is_direct_query():
                events_table = database.get_table("events")
                poe = cast(VirtualTable, events_table.fields["poe"])

                if modifiers.personsOnEventsMode == PersonsOnEventsMode.DISABLED:
                    # no change
                    events_table.fields["person"] = FieldTraverser(chain=["pdi", "person"])
                    events_table.fields["person_id"] = FieldTraverser(chain=["pdi", "person_id"])

                elif modifiers.personsOnEventsMode == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS:
                    events_table.fields["person_id"] = StringDatabaseField(name="person_id")
                    _use_person_properties_from_events(database)

                elif modifiers.personsOnEventsMode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS:
                    _use_person_id_from_person_overrides(database)
                    _use_person_properties_from_events(database)
                    poe.fields["id"] = events_table.fields["person_id"]

                elif modifiers.personsOnEventsMode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED:
                    _use_person_id_from_person_overrides(database)
                    events_table.fields["person"] = LazyJoin(
                        from_field=["person_id"],
                        join_table=database.get_table("persons"),
                        resolver=PERSONS,
                    )

                _use_error_tracking_issue_id_from_error_tracking_issue_overrides(database)

        with timings.measure("session_table", emit_span=True):
            if not database._is_direct_query() and (
                modifiers.sessionTableVersion == SessionTableVersion.V2
                or modifiers.sessionTableVersion == SessionTableVersion.AUTO
            ):
                raw_sessions: Union[RawSessionsTableV2, RawSessionsTableV3] = RawSessionsTableV2()
                database.tables.add_child(
                    TableNode(name="raw_sessions", table=raw_sessions), table_conflict_mode="override"
                )

                sessions: Union[SessionsTableV2, SessionsTableV3] = SessionsTableV2()
                database.tables.add_child(TableNode(name="sessions", table=sessions), table_conflict_mode="override")

                events_table = database.get_table("events")
                events_table.fields["session"] = LazyJoin(
                    from_field=["$session_id"],
                    join_table=sessions,
                    resolver=EVENTS_TO_SESSIONS_V2,
                )

                replay_events = database.get_table("session_replay_events")
                replay_events.fields["session"] = LazyJoin(
                    from_field=["session_id"],
                    join_table=sessions,
                    resolver=REPLAY_TO_SESSIONS_V2,
                )
                cast(LazyJoin, replay_events.fields["events"]).join_table = events_table

                raw_replay_events = database.get_table("raw_session_replay_events")
                raw_replay_events.fields["session"] = LazyJoin(
                    from_field=["session_id"],
                    join_table=sessions,
                    resolver=REPLAY_TO_SESSIONS_V2,
                )
                cast(LazyJoin, raw_replay_events.fields["events"]).join_table = events_table
            elif not database._is_direct_query() and modifiers.sessionTableVersion == SessionTableVersion.V3:
                sessions = SessionsTableV3()
                database.tables.add_child(TableNode(name="sessions", table=sessions), table_conflict_mode="override")

                events_table = database.get_table("events")
                events_table.fields["session"] = LazyJoin(
                    from_field=["$session_id"],
                    join_table=sessions,
                    resolver=EVENTS_TO_SESSIONS_V3,
                )

                replay_events = database.get_table("session_replay_events")
                replay_events.fields["session"] = LazyJoin(
                    from_field=["session_id"],
                    join_table=sessions,
                    resolver=REPLAY_TO_SESSIONS_V3,
                )
                cast(LazyJoin, replay_events.fields["events"]).join_table = events_table

                raw_replay_events = database.get_table("raw_session_replay_events")
                raw_replay_events.fields["session"] = LazyJoin(
                    from_field=["session_id"],
                    join_table=sessions,
                    resolver=REPLAY_TO_SESSIONS_V3,
                )
                cast(LazyJoin, raw_replay_events.fields["events"]).join_table = events_table

        with timings.measure("virtual_fields", emit_span=True):
            if not database._is_direct_query():
                _use_virtual_fields(database, modifiers, timings)

        with timings.measure("group_type_mapping", emit_span=True):
            if not database._is_direct_query():
                group_types = sources.group_types
                _setup_group_key_fields(database, group_types)
                events_table = database.get_table("events")
                for mapping in group_types:
                    if events_table.fields.get(mapping["group_type"]) is None:
                        events_table.fields[mapping["group_type"]] = FieldTraverser(
                            chain=[f"group_{mapping['group_type_index']}"]
                        )

        warehouse_tables_dot_notation_mapping: dict[str, str] = {}
        warehouse_tables: TableNode = TableNode()
        self_managed_warehouse_tables: TableNode = TableNode()
        views: TableNode = TableNode()
        warehouse_tables_to_process: list[tuple[Table, DataWarehouseTable]] = []

        with timings.measure("data_warehouse_saved_query", emit_span=True):
            for saved_query in sources.saved_queries:
                with timings.measure(f"saved_query_{saved_query.name}"):
                    if (
                        sources.is_hogql_warehouse_access_control_enabled
                        and not sources.bypass_warehouse_access_control
                        and database._is_warehouse_view_denied(saved_query)
                    ):
                        continue
                    views.add_child(
                        TableNode.create_nested_for_chain(
                            saved_query.name.split("."),
                            table=saved_query.hogql_definition(modifiers),
                        ),
                        table_conflict_mode="ignore",
                    )

        with timings.measure("endpoint_saved_query", emit_span=True):
            if not database._is_direct_query():
                try:
                    for endpoint_saved_query in sources.endpoint_saved_queries:
                        with timings.measure(f"endpoint_saved_query_{endpoint_saved_query.name}"):
                            # Endpoint-origin saved queries are a separate list, so they're checked too
                            if (
                                sources.is_hogql_warehouse_access_control_enabled
                                and not sources.bypass_warehouse_access_control
                                and database._is_warehouse_view_denied(endpoint_saved_query)
                            ):
                                continue
                            views.add_child(
                                TableNode(
                                    name=endpoint_saved_query.name,
                                    table=endpoint_saved_query.hogql_definition(modifiers),
                                ),
                                table_conflict_mode="ignore",
                            )
                except Exception as e:
                    capture_exception(e)

        with timings.measure("revenue_analytics_views", emit_span=True):
            if not database._is_direct_query():
                # Each view will have a name similar to `stripe.<prefix>.<table_name>`
                # We want to create a nested table group where `stripe` is the parent,
                # `<prefix>` is the child of `stripe`, and `<table_name>` is the child of `<prefix>`
                # allowing you to access the table as `stripe[prefix][table_name]` in a dict fashion
                # but still allowing the bare `stripe.prefix.table_name` string access
                for view in sources.revenue_views:
                    try:
                        views.add_child(TableNode.create_nested_for_chain(view.name.split("."), view))
                    except Exception as e:
                        capture_exception(e)
                        continue

        with timings.measure("data_warehouse_tables", emit_span=True):

            class WarehousePropertiesVirtualTable(VirtualTable):
                fields: dict[str, FieldOrTable]
                parent_table: Table

                def to_printed_hogql(self):
                    return self.parent_table.to_printed_hogql()

                def to_printed_clickhouse(self, context):
                    return self.parent_table.to_printed_clickhouse(context)

            with timings.measure("build_tables", emit_span=True):
                sync_warnings_now = datetime.now(UTC)
                for table in sources.warehouse_tables:
                    if (
                        not database._is_direct_query()
                        and table.external_data_source
                        and table.external_data_source.access_method == ExternalDataSource.AccessMethod.DIRECT
                    ):
                        continue

                    if (
                        sources.is_hogql_warehouse_access_control_enabled
                        and not sources.bypass_warehouse_access_control
                        and database._is_warehouse_table_denied(table)
                    ):
                        continue

                    with timings.measure(f"table_{table.name}"):
                        s3_table = table.hogql_definition(modifiers)

                        sync_warnings = get_warehouse_sync_warnings(table, now=sync_warnings_now)
                        if sync_warnings:
                            database._data_warehouse_sync_warnings[str(table.id)] = sync_warnings
                        primary_table = s3_table

                        # If the warehouse table has no _properties_ field, then set it as a virtual table
                        if s3_table.fields.get("properties") is None:
                            s3_table.fields["properties"] = WarehousePropertiesVirtualTable(
                                fields=s3_table.fields, parent_table=s3_table, hidden=True
                            )

                        if table.external_data_source:
                            if not database._is_direct_query():
                                warehouse_tables.add_child(TableNode(name=table.name, table=s3_table))
                        else:
                            self_managed_warehouse_tables.add_child(TableNode(name=table.name, table=s3_table))

                        if table.external_data_source:
                            for index, table_key in enumerate(
                                _get_warehouse_table_keys(table, direct_query=database._is_direct_query())
                            ):
                                table_for_key = s3_table if index == 0 else s3_table.model_copy(deep=True)
                                table_chain = table_key.split(".")
                                table_conflict_mode: Literal["override", "ignore"] = (
                                    "override"
                                    if database._is_direct_query()
                                    and table.external_data_source
                                    and table.external_data_source.access_method
                                    == ExternalDataSource.AccessMethod.DIRECT
                                    else "ignore"
                                )

                                # For a chain of type a.b.c, we want to create a nested table node
                                # where a is the parent, b is the child of a, and c is the child of b
                                # where a.b.c will contain the table.
                                # Snowflake stores identifiers uppercase but resolves them
                                # case-insensitively, so mark its nodes so `from tpch_sf1.nation`
                                # (any case) resolves to the canonical `TPCH_SF1.NATION`.
                                warehouse_tables.add_child(
                                    TableNode.create_nested_for_chain(
                                        table_chain,
                                        table_for_key,
                                        case_insensitive=table.external_data_source.is_direct_snowflake,
                                    ),
                                    table_conflict_mode=table_conflict_mode,
                                )

                                joined_table_chain = ".".join(table_chain)
                                table_for_key.name = joined_table_chain
                                warehouse_tables_dot_notation_mapping[joined_table_chain] = table.name
                                if table.external_data_source.access_method == ExternalDataSource.AccessMethod.DIRECT:
                                    database._direct_access_warehouse_table_names.add(joined_table_chain)
                                if index == 0:
                                    primary_table = table_for_key

                        warehouse_tables_to_process.append((primary_table, table))

        db_span.set_attribute("warehouse_table_count", len(sources.warehouse_tables))

        # Index warehouse table models by name, newest wins, mirroring the eager path's `.latest()`.
        warehouse_table_models_by_name: dict[str, DataWarehouseTable] = {}
        for warehouse_table_model in sources.warehouse_tables:
            existing = warehouse_table_models_by_name.get(warehouse_table_model.name)
            if existing is None or warehouse_table_model.created_at > existing.created_at:
                warehouse_table_models_by_name[warehouse_table_model.name] = warehouse_table_model

        def define_mappings(
            root_node: TableNode,
            get_table: Callable[[Any], Union[DataWarehouseTable, "DataWarehouseSavedQuery"]],
        ) -> TableNode:
            table: Table | None = None

            if root_node.has_child([warehouse_modifier.table_name]):
                _table = root_node.get_child([warehouse_modifier.table_name]).get()
                assert isinstance(_table, Table)

                table = _table

            if "." in warehouse_modifier.table_name:
                table_chain = warehouse_modifier.table_name.split(".")
                if not root_node.has_child(table_chain):
                    return root_node

                _table = root_node.get_child(table_chain).get()
                assert isinstance(_table, Table)

                table = _table

            if table is None:
                return root_node

            # The configured `id_field` must win even when the source table has its own column
            # literally named `id`. Without this guard the virtual mapping is skipped and queries
            # silently resolve to the table's own `id` column instead of the configured field.
            id_field_is_remapped = warehouse_modifier.id_field != "id"
            if id_field_is_remapped or "id" not in table.fields.keys():
                table.fields["id"] = ExpressionField(
                    name="id",
                    expr=parse_expr(warehouse_modifier.id_field),
                )

            table_has_no_timestamp_field = "timestamp" not in table.fields.keys()
            timestamp_field_is_datetime = isinstance(table.fields.get("timestamp"), DateTimeDatabaseField)
            # The configured timestamp_field must win even when the source table has its own DateTime
            # column literally named `timestamp` (e.g. an ingestion timestamp). Without this, the virtual
            # mapping is skipped and queries silently bucket/filter on the wrong column.
            timestamp_field_is_remapped = warehouse_modifier.timestamp_field != "timestamp"

            if timestamp_field_is_remapped or table_has_no_timestamp_field or not timestamp_field_is_datetime:
                # get_table raises (rather than skipping) when no backing row exists — see resolvers below.
                table_model = get_table(warehouse_modifier)
                timestamp_field_type = table_model.get_clickhouse_column_type(warehouse_modifier.timestamp_field)
                modifier_timestamp_field_is_timestamp = warehouse_modifier.timestamp_field == "timestamp"

                # If field type is none or datetime, we can use the field directly
                if timestamp_field_type is None or timestamp_field_type.startswith("DateTime"):
                    if modifier_timestamp_field_is_timestamp:
                        table.fields["timestamp"] = DateTimeDatabaseField(name="timestamp")
                    else:
                        table.fields["timestamp"] = ExpressionField(
                            name="timestamp",
                            expr=ast.Field(chain=[warehouse_modifier.timestamp_field]),
                        )
                else:
                    if modifier_timestamp_field_is_timestamp:
                        table.fields["timestamp"] = UnknownDatabaseField(name="timestamp")
                    else:
                        table.fields["timestamp"] = ExpressionField(
                            name="timestamp",
                            expr=ast.Call(
                                name="toDateTime", args=[ast.Field(chain=[warehouse_modifier.timestamp_field])]
                            ),
                        )

            # As with `id` and `timestamp` above, the configured `distinct_id_field` must win over a
            # source column literally named `distinct_id`; otherwise the virtual mapping is skipped and
            # the wrong column is used silently.
            distinct_id_field_is_remapped = warehouse_modifier.distinct_id_field != "distinct_id"
            if distinct_id_field_is_remapped or "distinct_id" not in table.fields.keys():
                table.fields["distinct_id"] = ExpressionField(
                    name="distinct_id",
                    expr=parse_expr(warehouse_modifier.distinct_id_field),
                )

            # person_id is deliberately left as "inject only when absent": the modifier has no
            # person_id_field to remap from, and a source column literally named `person_id` is
            # plausibly authoritative (e.g. an already-resolved person UUID), so it should win. When
            # the table has no `person_id`, derive it from the events join if one exists, else fall
            # back to the configured distinct_id_field.
            if "person_id" not in table.fields.keys():
                events_join = next(
                    (
                        join
                        for join in sources.data_warehouse_joins
                        if join.source_table_name == warehouse_modifier.table_name
                        and join.joining_table_name == "events"
                    ),
                    None,
                )
                if events_join:
                    table.fields["person_id"] = FieldTraverser(chain=[events_join.field_name, "person_id"])
                else:
                    table.fields["person_id"] = ExpressionField(
                        name="person_id",
                        expr=parse_expr(warehouse_modifier.distinct_id_field),
                    )

            return root_node

        # Resolve a modifier's table model from already-fetched sources, raising DoesNotExist when no
        # row matches just as the eager path's `.latest()` did.
        def _saved_query_model_for(wm: Any) -> "DataWarehouseSavedQuery":
            saved_query = sources.event_modifier_saved_queries.get(wm.table_name)
            if saved_query is None:
                raise DataWarehouseSavedQuery.DoesNotExist(
                    f"No DataWarehouseSavedQuery for dataWarehouseEventsModifier table '{wm.table_name}'"
                )
            return saved_query

        def _warehouse_table_model_for(wm: Any) -> DataWarehouseTable:
            name = warehouse_tables_dot_notation_mapping.get(wm.table_name, wm.table_name)
            warehouse_table = warehouse_table_models_by_name.get(name)
            if warehouse_table is None:
                raise DataWarehouseTable.DoesNotExist(
                    f"No DataWarehouseTable for dataWarehouseEventsModifier table '{wm.table_name}'"
                )
            return warehouse_table

        def _self_managed_table_model_for(wm: Any) -> DataWarehouseTable:
            warehouse_table = warehouse_table_models_by_name.get(wm.table_name)
            if warehouse_table is None:
                raise DataWarehouseTable.DoesNotExist(
                    f"No DataWarehouseTable for dataWarehouseEventsModifier table '{wm.table_name}'"
                )
            return warehouse_table

        if modifiers.dataWarehouseEventsModifiers:
            with timings.measure("data_warehouse_event_modifiers", emit_span=True):
                for warehouse_modifier in modifiers.dataWarehouseEventsModifiers:
                    with timings.measure(f"data_warehouse_event_modifier_{warehouse_modifier.table_name}"):
                        # Apply mappings to every matching namespace. A saved query and a warehouse table can share a
                        # name, and the final database may resolve that name to the table even if a view exists too.
                        views = define_mappings(views, _saved_query_model_for)
                        warehouse_tables = define_mappings(warehouse_tables, _warehouse_table_model_for)
                        self_managed_warehouse_tables = define_mappings(
                            self_managed_warehouse_tables, _self_managed_table_model_for
                        )

        database._add_warehouse_tables(warehouse_tables)
        database._add_warehouse_self_managed_tables(self_managed_warehouse_tables)
        database._add_views(views)

        if build_postgres_foreign_keys:
            with timings.measure("warehouse_foreign_keys", emit_span=True):
                for hogql_table, warehouse_table_model in warehouse_tables_to_process:
                    add_postgres_foreign_key_lazy_joins(
                        hogql_table=hogql_table,
                        warehouse_table=warehouse_table_model,
                        database=database,
                        schemas=_get_active_external_data_schemas(warehouse_table_model),
                    )

        with timings.measure("data_warehouse_joins", emit_span=True):
            for join in sources.data_warehouse_joins:
                # Skip if either table is not present. This can happen if the table was deleted after the join was created.
                # User will be prompted on UI to resolve missing tables underlying the JOIN
                if not database.has_table(join.source_table_name) or not database.has_table(join.joining_table_name):
                    continue

                try:
                    source_table = database.get_table(join.source_table_name)
                    joining_table = database.get_table(join.joining_table_name)

                    from_field = get_join_field_chain(join.source_table_key)
                    if from_field is None:
                        continue

                    to_field = get_join_field_chain(join.joining_table_key)
                    if to_field is None:
                        continue

                    join_configuration = join.configuration if isinstance(join.configuration, dict) else {}
                    use_experiments = bool(
                        join.joining_table_name == "events" and join_configuration.get("experiments_optimized")
                    )
                    dw_join_kwargs: dict[str, Any] = {
                        "source_table_key": join.source_table_key,
                        "joining_table_key": join.joining_table_key,
                        "joining_table_name": join.joining_table_name,
                        "configuration": join_configuration,
                    }
                    source_table.fields[join.field_name] = LazyJoin(
                        from_field=from_field,
                        to_field=to_field,
                        join_table=joining_table,
                        resolver=DATA_WAREHOUSE_EXPERIMENTS if use_experiments else DATA_WAREHOUSE,
                        resolver_params=data_warehouse_resolver_params(**dw_join_kwargs),
                    )

                    if not database._is_direct_query() and join.source_table_name == "persons":
                        events_table = database.get_table("events")
                        person_field = events_table.fields["person"]
                        if isinstance(person_field, ast.FieldTraverser):
                            table_or_field: ast.FieldOrTable = events_table
                            for chain in person_field.chain:
                                if isinstance(table_or_field, ast.LazyJoin):
                                    table_or_field = table_or_field.resolve_table(
                                        HogQLContext(team_id=team_id, database=database)
                                    )
                                    if table_or_field.has_field(chain):
                                        table_or_field = table_or_field.get_field(chain)
                                        if isinstance(table_or_field, ast.LazyJoin):
                                            table_or_field = table_or_field.resolve_table(
                                                HogQLContext(team_id=team_id, database=database)
                                            )
                                elif isinstance(table_or_field, ast.Table):
                                    table_or_field = table_or_field.get_field(chain)

                            assert isinstance(table_or_field, ast.Table)

                            if isinstance(table_or_field, ast.VirtualTable):
                                table_or_field.fields[join.field_name] = ast.FieldTraverser(
                                    chain=["..", join.field_name]
                                )

                                override_source_table_key = f"person.{join.source_table_key}"

                                source_table_key_node = qualify_join_key_expr(join.source_table_key, "person")
                                if source_table_key_node is not None:
                                    override_source_table_key = source_table_key_node.to_hogql()

                                events_table.fields[join.field_name] = LazyJoin(
                                    from_field=from_field,
                                    to_field=to_field,
                                    join_table=joining_table,
                                    # reusing the data-warehouse resolver but with a different source_table_key
                                    # since we're joining 'directly' on events
                                    resolver=DATA_WAREHOUSE,
                                    resolver_params=data_warehouse_resolver_params(
                                        **dw_join_kwargs, override_source_table_key=override_source_table_key
                                    ),
                                )
                            else:
                                table_or_field.fields[join.field_name] = LazyJoin(
                                    from_field=from_field,
                                    to_field=to_field,
                                    join_table=joining_table,
                                    resolver=DATA_WAREHOUSE,
                                    resolver_params=data_warehouse_resolver_params(**dw_join_kwargs),
                                )
                        elif isinstance(person_field, ast.LazyJoin):
                            person_field.join_table.fields[join.field_name] = LazyJoin(  # type: ignore
                                from_field=from_field,
                                to_field=to_field,
                                join_table=joining_table,
                                resolver=DATA_WAREHOUSE,
                                resolver_params=data_warehouse_resolver_params(**dw_join_kwargs),
                            )

                except Exception as e:
                    capture_exception(e)

        database.apply_schema_scope()

        return database


def get_data_warehouse_table_name(source: ExternalDataSource | None, table_name: str):
    if source is None:
        return table_name

    if source.access_method == ExternalDataSource.AccessMethod.DIRECT:
        return table_name

    source_type = source.source_type.lower()
    prefix = (source.prefix or "").strip("_").lower()
    table_name_stripped = _strip_external_source_prefix(source, table_name)

    if prefix:
        return f"{source_type}.{prefix}.{table_name_stripped}".lower()

    return f"{source_type}.{table_name_stripped}".lower()


def _use_person_properties_from_events(database: Database) -> None:
    database.get_table("events").fields["person"] = FieldTraverser(chain=["poe"])


def _use_person_id_from_person_overrides(database: Database) -> None:
    table = database.get_table("events")
    table.fields["event_person_id"] = StringDatabaseField(name="person_id")
    table.fields["override"] = LazyJoin(
        from_field=["distinct_id"],
        join_table=database.get_table("person_distinct_id_overrides"),
        resolver=PERSON_DISTINCT_ID_OVERRIDES,
    )
    table.fields["person_id"] = ExpressionField(
        name="person_id",
        expr=parse_expr(
            # NOTE: assumes `join_use_nulls = 0` (the default), as ``override.distinct_id`` is not Nullable
            "if(not(empty(override.distinct_id)), override.person_id, event_person_id)",
            start=None,
        ),
        isolate_scope=True,
    )


@cache
def _error_tracking_event_exprs() -> dict[str, ast.Expr]:
    # Parsed once, copy.deepcopy'd per use (the resolver mutates exprs in place); these fall under
    # the parser's min-cacheable length, so they would otherwise re-parse on every build.
    return {
        "event_issue_id": parse_expr("toUUID(properties.$exception_issue_id)"),
        # NOTE: assumes `join_use_nulls = 0` (the default), as ``override.fingerprint`` is not Nullable
        "issue_id": parse_expr(
            "if(not(empty(exception_issue_override.issue_id)), exception_issue_override.issue_id, event_issue_id)",
            start=None,
        ),
        "issue_id_v2": parse_expr("fingerprint_issue_state.issue_id", start=None),
        "issue_name": parse_expr("fingerprint_issue_state.issue_name", start=None),
        "issue_description": parse_expr("fingerprint_issue_state.issue_description", start=None),
        "issue_status": parse_expr("fingerprint_issue_state.issue_status", start=None),
        "issue_assigned_user_id": parse_expr("fingerprint_issue_state.assigned_user_id", start=None),
        "issue_assigned_role_id": parse_expr("fingerprint_issue_state.assigned_role_id", start=None),
        "issue_first_seen": parse_expr("fingerprint_issue_state.first_seen", start=None),
    }


def _use_error_tracking_issue_id_from_error_tracking_issue_overrides(database: Database) -> None:
    exprs = copy.deepcopy(_error_tracking_event_exprs())
    table = database.get_table("events")
    # convert event_issue_id to UUID to match type of `issue_id` on the overrides table
    table.fields["event_issue_id"] = ExpressionField(name="event_issue_id", expr=exprs["event_issue_id"])
    table.fields["exception_issue_override"] = LazyJoin(
        from_field=["fingerprint"],
        join_table=ErrorTrackingIssueFingerprintOverridesTable(),
        resolver=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES,
    )
    table.fields["issue_id"] = ExpressionField(name="issue_id", expr=exprs["issue_id"])

    # Issue metadata from the fingerprint_issue_state table
    table.fields["fingerprint_issue_state"] = LazyJoin(
        from_field=["fingerprint"],
        join_table=ErrorTrackingFingerprintIssueStateTable(),
        resolver=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
    )
    table.fields["issue_id_v2"] = ExpressionField(name="issue_id_v2", expr=exprs["issue_id_v2"])
    table.fields["issue_name"] = ExpressionField(name="issue_name", expr=exprs["issue_name"])
    table.fields["issue_description"] = ExpressionField(name="issue_description", expr=exprs["issue_description"])
    table.fields["issue_status"] = ExpressionField(name="issue_status", expr=exprs["issue_status"])
    table.fields["issue_assigned_user_id"] = ExpressionField(
        name="issue_assigned_user_id", expr=exprs["issue_assigned_user_id"]
    )
    table.fields["issue_assigned_role_id"] = ExpressionField(
        name="issue_assigned_role_id", expr=exprs["issue_assigned_role_id"]
    )
    table.fields["issue_first_seen"] = ExpressionField(name="issue_first_seen", expr=exprs["issue_first_seen"])


def _setup_group_key_fields(database: Database, group_types: list[dict[str, Any]]) -> None:
    """
    Set up group key fields as ExpressionFields that handle filtering based on GroupTypeMapping.created_at.
    For $group_N fields, this returns:
    - Empty string if no GroupTypeMapping exists for that index
    - if(timestamp < mapping.created_at, '', $group_N) if GroupTypeMapping exists
    """
    group_mappings = {mapping["group_type_index"]: mapping for mapping in group_types}
    table = database.get_table("events")

    for group_index in range(5):
        field_name = f"$group_{group_index}"

        group_mapping = group_mappings.get(group_index, None)
        # If no mapping exists or the mapping predated this feature, leave the original field unchanged
        if group_mapping and group_mapping["created_at"]:
            # Store the original field as a "raw" version before replacing
            original_field = table.fields[field_name]
            raw_field_name = f"_{field_name}_raw"
            table.fields[raw_field_name] = original_field.model_copy(update={"hidden": True})

            # Must stay a datetime constant: a naive string literal would be parsed by ClickHouse in the
            # project's timezone (the comparison is against toTimeZone(timestamp, <project tz>)), shifting
            # the cutoff by the project's UTC offset.
            created_at = group_mapping["created_at"]
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)

            table.fields[field_name] = ExpressionField(
                name=field_name,
                expr=ast.Call(
                    name="if",
                    args=[
                        ast.CompareOperation(
                            left=ast.Field(chain=["timestamp"]),
                            op=ast.CompareOperationOp.Lt,
                            right=ast.Constant(value=created_at),
                        ),
                        ast.Constant(value=""),
                        ast.Field(chain=[raw_field_name]),
                    ],
                ),
                isolate_scope=True,
            )


def _use_virtual_fields(database: Database, modifiers: "HogQLQueryModifiers", timings: HogQLTimings) -> None:
    events_table = database.get_table("events")
    persons_table = database.get_table("persons")
    groups_table = database.get_table("groups")
    poe = cast(VirtualTable, events_table.fields["poe"])

    with timings.measure("initial_referring_domain_type"):
        field_name = "$virt_initial_referring_domain_type"
        persons_table.fields[field_name] = create_initial_domain_type(name=field_name, timings=timings)
        poe.fields[field_name] = create_initial_domain_type(
            name=field_name,
            timings=timings,
            properties_path=["poe", "properties"],
        )
    with timings.measure("initial_channel_type"):
        field_name = "$virt_initial_channel_type"
        persons_table.fields[field_name] = create_initial_channel_type(
            name=field_name, custom_rules=modifiers.customChannelTypeRules, timings=timings
        )
        poe.fields[field_name] = create_initial_channel_type(
            name=field_name,
            custom_rules=modifiers.customChannelTypeRules,
            timings=timings,
            properties_path=["poe", "properties"],
        )

    with timings.measure("traffic_type_virtual_fields"):
        from posthog.hogql.database.schema.traffic_type import (
            create_bot_name_field,
            create_bot_operator_field,
            create_is_bot_field,
            create_traffic_category_field,
            create_traffic_type_field,
        )

        for field_name, factory_fn in [
            ("$virt_is_bot", create_is_bot_field),
            ("$virt_traffic_type", create_traffic_type_field),
            ("$virt_traffic_category", create_traffic_category_field),
            ("$virt_bot_name", create_bot_name_field),
            ("$virt_bot_operator", create_bot_operator_field),
        ]:
            events_table.fields[field_name] = factory_fn(name=field_name)

    revenue_fields = ["revenue", "mrr"]
    with timings.measure("revenue_analytics_virtual_fields"):
        for field in revenue_fields:
            with timings.measure(field):
                field_name = f"$virt_{field}"
                chain = ["revenue_analytics", field]

                persons_table.fields[field_name] = ast.FieldTraverser(chain=chain)
                groups_table.fields[field_name] = ast.FieldTraverser(chain=chain)
                poe.fields[field_name] = ast.FieldTraverser(chain=chain)


def _constant_type_to_serialized_field_type(constant_type: ast.ConstantType) -> DatabaseSerializedFieldType | None:
    if isinstance(constant_type, ast.StringType):
        return DatabaseSerializedFieldType.STRING
    if isinstance(constant_type, ast.BooleanType):
        return DatabaseSerializedFieldType.BOOLEAN
    if isinstance(constant_type, ast.DateType):
        return DatabaseSerializedFieldType.DATE
    if isinstance(constant_type, ast.DateTimeType):
        return DatabaseSerializedFieldType.DATETIME
    if isinstance(constant_type, ast.UUIDType):
        return DatabaseSerializedFieldType.STRING
    if isinstance(constant_type, ast.ArrayType):
        return DatabaseSerializedFieldType.ARRAY
    if isinstance(constant_type, ast.TupleType):
        return DatabaseSerializedFieldType.JSON
    if isinstance(constant_type, ast.IntegerType):
        return DatabaseSerializedFieldType.INTEGER
    if isinstance(constant_type, ast.FloatType):
        return DatabaseSerializedFieldType.FLOAT
    if isinstance(constant_type, ast.DecimalType):
        return DatabaseSerializedFieldType.DECIMAL
    return None


HOGQL_CHARACTERS_TO_BE_WRAPPED = ["@", "-", "!", "$", "+"]
NOT_DELETED_Q = Q(deleted=False) | Q(deleted__isnull=True)


def _attach_external_data_sources(
    warehouse_tables: Sequence[DataWarehouseTable], *, team_id: int, defer_job_inputs: bool = True
) -> None:
    """Prime each table's `external_data_source` FK from one bulk fetch of the distinct sources.

    Tables outnumber their sources by ~100x, and `job_inputs` is an `EncryptedJSONField` whose every
    leaf is Fernet-decrypted on hydration — so joining the source per row would decrypt the same few
    sources thousands of times, for data only the direct-postgres branch reads. `job_inputs` is
    deferred by default; callers that build that branch (direct-query mode) pass defer_job_inputs=False
    so the few sources they hydrate keep it loaded rather than lazily reloading it per table.
    """
    source_ids = {
        table.external_data_source_id for table in warehouse_tables if table.external_data_source_id is not None
    }
    sources_by_id: dict[Any, ExternalDataSource] = {}
    if source_ids:
        query = ExternalDataSource.objects.filter(team_id=team_id, id__in=source_ids)
        if defer_job_inputs:
            query = query.defer("job_inputs")
        sources_by_id = {source.pk: source for source in query}
    for table in warehouse_tables:
        if table.external_data_source_id is None:
            continue
        # queryable() guarantees a live source row for any set source_id, so the lookup hits; we still
        # guard so a hard-delete race leaves the FK to lazy-load rather than caching a wrong object.
        source = sources_by_id.get(table.external_data_source_id)
        if source is not None:
            table.external_data_source = source


def _preload_active_external_data_schemas(warehouse_tables: Sequence[DataWarehouseTable]) -> None:
    tables_by_id = {
        str(warehouse_table.id): warehouse_table
        for warehouse_table in warehouse_tables
        if warehouse_table.external_data_source_id
    }
    if not tables_by_id:
        return

    schemas_by_table_id: dict[str, list[ExternalDataSchema]] = defaultdict(list)
    # Reuse the owning table's already-hydrated source instead of joining it per schema, which would
    # re-decrypt job_inputs on the same few sources thousands of times.
    for schema in ExternalDataSchema.objects.filter(NOT_DELETED_Q, table_id__in=list(tables_by_id.keys())):
        owning_table = tables_by_id.get(str(schema.table_id))
        owning_source = owning_table.external_data_source if owning_table is not None else None
        if owning_source is not None and schema.source_id == owning_source.pk:
            schema.source = owning_source
        schemas_by_table_id[str(schema.table_id)].append(schema)

    for warehouse_table in warehouse_tables:
        warehouse_table.__dict__["_active_external_data_schemas"] = schemas_by_table_id.get(str(warehouse_table.id), [])


def _attach_decrypted_credentials(warehouse_tables: Sequence[DataWarehouseTable], *, team_id: int) -> None:
    """Prime each table's `credential` FK from one bulk fetch of the distinct credentials.

    Tables and views share a handful of credentials, so a bulk fetch keeps Fernet decryption to
    O(credentials) instead of the O(tables) a per-row join would cost.
    """
    credential_ids = {table.credential_id for table in warehouse_tables if table.credential_id is not None}
    credentials_by_id: dict[Any, DataWarehouseCredential] = {}
    if credential_ids:
        credentials_by_id = {
            credential.pk: credential
            for credential in DataWarehouseCredential.objects.filter(team_id=team_id, id__in=credential_ids)
        }
    for table in warehouse_tables:
        table.credential = credentials_by_id.get(table.credential_id) if table.credential_id is not None else None


def _get_active_external_data_schemas(warehouse_table: DataWarehouseTable) -> list[ExternalDataSchema]:
    active_external_data_schemas = cast(
        Optional[list[ExternalDataSchema]],
        getattr(warehouse_table, "_active_external_data_schemas", None),
    )
    if active_external_data_schemas is not None:
        return active_external_data_schemas

    if warehouse_table.external_data_source_id is None:
        return []

    return list(ExternalDataSchema.objects.filter(NOT_DELETED_Q, table_id=warehouse_table.id))


def _strip_external_source_prefix(source: ExternalDataSource, table_name: str) -> str:
    source_type = source.source_type.lower()
    raw_prefix = (source.prefix or "").lower()
    prefix = raw_prefix.strip("_")

    table_name_stripped = table_name
    known_prefixes = [
        f"{source_type}_{source.pk.hex}_",
        f"{raw_prefix}{source_type}_" if raw_prefix else None,
        f"{prefix}_{source_type}_" if prefix else None,
        f"{prefix}{source_type}_" if prefix else None,
        f"{source_type}_",
    ]

    for known_prefix in filter(None, known_prefixes):
        if table_name_stripped.lower().startswith(known_prefix):
            table_name_stripped = table_name_stripped[len(known_prefix) :]
            break

    return table_name_stripped


def _get_warehouse_table_keys(warehouse_table: DataWarehouseTable, *, direct_query: bool) -> list[str]:
    source = warehouse_table.external_data_source
    if source is not None and source.access_method == ExternalDataSource.AccessMethod.DIRECT and direct_query:
        return [warehouse_table.name]

    return [get_data_warehouse_table_name(source, warehouse_table.name)]


def _should_include_connection_table(
    warehouse_table: DataWarehouseTable,
    *,
    connection_id: str,
) -> bool:
    source = warehouse_table.external_data_source
    if source is None or source.access_method != ExternalDataSource.AccessMethod.DIRECT:
        return False

    if str(warehouse_table.external_data_source_id) != connection_id:
        return False

    schemas = _get_active_external_data_schemas(warehouse_table)
    return not schemas or any(schema.should_sync for schema in schemas)


def _schema_field_input(table: Table) -> dict[str, Any]:
    """Fields to surface in the serialized schema (SQL editor sidebar, autocomplete).

    `get_asterisk()` exists for `SELECT *` expansion, so it drops lazy joins, virtual tables,
    and field traversers — but those are exactly the relational fields users need to see in the
    schema. Add them back while preserving `get_asterisk`'s column filtering (`avoid_asterisk_fields`
    and hidden columns), so data warehouse joins show up on `FunctionCallTable`-backed tables like
    the `system.*` Postgres tables.
    """
    if not isinstance(table, FunctionCallTable):
        return table.fields

    field_input = table.get_asterisk()
    for key, field in table.fields.items():
        if key not in field_input and isinstance(field, (LazyJoin, Table, FieldTraverser)):
            field_input[key] = field
    return field_input


def serialize_fields(
    field_input,
    context: HogQLContext,
    table_chain: list[str],
    db_columns: DataWarehouseTableColumns | None = None,
    table_type: Literal["posthog"] | Literal["external"] = "posthog",
) -> list["DatabaseSchemaField"]:
    from posthog.schema import DatabaseSchemaField  # noqa: PLC0415

    from posthog.hogql.resolver import resolve_types_from_table

    field_output: list[DatabaseSchemaField] = []
    for field_key, field in field_input.items():
        try:
            if db_columns is not None:
                column = db_columns[field_key]
                if isinstance(column, str):
                    schema_valid = True
                else:
                    schema_valid = cast(bool, column.get("valid", True))
            else:
                schema_valid = True
        except KeyError:
            # We redefine fields on some sourced tables, causing the "hogql" and "clickhouse" field names to be intentionally out of sync
            schema_valid = True

        if any(n in field_key for n in HOGQL_CHARACTERS_TO_BE_WRAPPED):
            hogql_value = f"`{field_key}`"
        else:
            hogql_value = str(field_key)

        if isinstance(field, FieldOrTable):
            if field.hidden:
                continue

        if field_key == "team_id" and table_type == "posthog":
            pass
        elif isinstance(field, DatabaseField):
            if isinstance(field, IntegerDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.INTEGER,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, FloatDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.FLOAT,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, DecimalDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.DECIMAL,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, StringDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.STRING,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, UUIDDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.STRING,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, DateTimeDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.DATETIME,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, DateDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.DATE,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, BooleanDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.BOOLEAN,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, StringJSONDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.JSON,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, StructDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.JSON,
                        schema_valid=schema_valid,
                        fields=list(field.fields.keys()),
                    )
                )
            elif isinstance(field, StringArrayDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.ARRAY,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, UnknownDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.UNKNOWN,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, ExpressionField):
                field_expr = resolve_types_from_table(field.expr, table_chain, context, "hogql")
                assert field_expr.type is not None
                constant_type = field_expr.type.resolve_constant_type(context)

                field_type = _constant_type_to_serialized_field_type(constant_type)
                if field_type is None:
                    field_type = DatabaseSerializedFieldType.EXPRESSION

                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=field_type,
                        schema_valid=schema_valid,
                    )
                )
        elif isinstance(field, LazyJoin):
            resolved_table = field.resolve_table(context)

            if isinstance(resolved_table, SavedQuery):
                type = DatabaseSerializedFieldType.VIEW
                id = str(resolved_table.id)
            else:
                type = DatabaseSerializedFieldType.LAZY_TABLE
                id = None

            field_output.append(
                DatabaseSchemaField(
                    name=field_key,
                    hogql_value=hogql_value,
                    type=type,
                    schema_valid=schema_valid,
                    table=field.resolve_table(context).to_printed_hogql(),
                    fields=list(field.resolve_table(context).fields.keys()),
                    id=id or field_key,
                )
            )
        elif isinstance(field, VirtualTable):
            field_output.append(
                DatabaseSchemaField(
                    name=field_key,
                    hogql_value=hogql_value,
                    type=DatabaseSerializedFieldType.VIRTUAL_TABLE,
                    schema_valid=schema_valid,
                    table=field.to_printed_hogql(),
                    fields=list(field.fields.keys()),
                )
            )
        elif isinstance(field, FieldTraverser):
            field_output.append(
                DatabaseSchemaField(
                    name=field_key,
                    hogql_value=hogql_value,
                    type=DatabaseSerializedFieldType.FIELD_TRAVERSER,
                    schema_valid=schema_valid,
                    chain=field.chain,
                )
            )
    return field_output
