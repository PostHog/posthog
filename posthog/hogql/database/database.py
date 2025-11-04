import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, Optional, Union, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Prefetch, Q

from opentelemetry import trace
from pydantic import BaseModel, ConfigDict

from posthog.schema import (
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaField,
    DatabaseSchemaManagedViewTable,
    DatabaseSchemaPostHogTable,
    DatabaseSchemaSchema,
    DatabaseSchemaSource,
    DatabaseSchemaSystemTable,
    DatabaseSchemaViewTable,
    DatabaseSerializedFieldType,
    HogQLQuery,
    HogQLQueryModifiers,
    PersonsOnEventsMode,
    SessionTableVersion,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
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
    Table,
    TableNode,
    UnknownDatabaseField,
    VirtualTable,
)
from posthog.hogql.database.schema.app_metrics2 import AppMetrics2Table
from posthog.hogql.database.schema.channel_type import create_initial_channel_type, create_initial_domain_type
from posthog.hogql.database.schema.cohort_people import CohortPeople, RawCohortPeople
from posthog.hogql.database.schema.document_embeddings import DocumentEmbeddingsTable, RawDocumentEmbeddingsTable
from posthog.hogql.database.schema.error_tracking_issue_fingerprint_overrides import (
    ErrorTrackingIssueFingerprintOverridesTable,
    RawErrorTrackingIssueFingerprintOverridesTable,
    join_with_error_tracking_issue_fingerprint_overrides_table,
)
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.exchange_rate import ExchangeRateTable
from posthog.hogql.database.schema.groups import GroupsTable, RawGroupsTable
from posthog.hogql.database.schema.groups_revenue_analytics import GroupsRevenueAnalyticsTable
from posthog.hogql.database.schema.heatmaps import HeatmapsTable
from posthog.hogql.database.schema.log_entries import (
    BatchExportLogEntriesTable,
    LogEntriesTable,
    ReplayConsoleLogsLogEntriesTable,
)
from posthog.hogql.database.schema.logs import LogsTable
from posthog.hogql.database.schema.numbers import NumbersTable
from posthog.hogql.database.schema.person_distinct_id_overrides import (
    PersonDistinctIdOverridesTable,
    RawPersonDistinctIdOverridesTable,
    join_with_person_distinct_id_overrides_table,
)
from posthog.hogql.database.schema.person_distinct_ids import PersonDistinctIdsTable, RawPersonDistinctIdsTable
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable, join_with_persons_table
from posthog.hogql.database.schema.persons_revenue_analytics import PersonsRevenueAnalyticsTable
from posthog.hogql.database.schema.pg_embeddings import PgEmbeddingsTable
from posthog.hogql.database.schema.query_log_archive import QueryLogArchiveTable, RawQueryLogArchiveTable
from posthog.hogql.database.schema.session_replay_events import (
    RawSessionReplayEventsTable,
    SessionReplayEventsTable,
    join_replay_table_to_sessions_table_v2,
    join_replay_table_to_sessions_table_v3,
)
from posthog.hogql.database.schema.sessions_v1 import RawSessionsTableV1, SessionsTableV1
from posthog.hogql.database.schema.sessions_v2 import (
    RawSessionsTableV2,
    SessionsTableV2,
    join_events_table_to_sessions_table_v2,
)
from posthog.hogql.database.schema.sessions_v3 import (
    RawSessionsTableV3,
    SessionsTableV3,
    join_events_table_to_sessions_table_v3,
)
from posthog.hogql.database.schema.static_cohort_people import StaticCohortPeople
from posthog.hogql.database.schema.system import SystemTables
from posthog.hogql.database.schema.web_analytics_preaggregated import (
    WebBouncesCombinedTable,
    WebBouncesDailyTable,
    WebBouncesHourlyTable,
    WebPreAggregatedBouncesTable,
    WebPreAggregatedStatsTable,
    WebStatsCombinedTable,
    WebStatsDailyTable,
    WebStatsHourlyTable,
)
from posthog.hogql.database.utils import get_join_field_chain
from posthog.hogql.errors import QueryError, ResolutionError
from posthog.hogql.parser import parse_expr
from posthog.hogql.timings import HogQLTimings

from posthog.exceptions_capture import capture_exception
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.team.team import WeekStartDay

from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.table import DataWarehouseTable, DataWarehouseTableColumns
from products.revenue_analytics.backend.views.orchestrator import build_all_revenue_analytics_views

if TYPE_CHECKING:
    from posthog.models import Team

tracer = trace.get_tracer(__name__)


@dataclasses.dataclass
class SerializedField:
    key: str
    name: str
    type: DatabaseSerializedFieldType
    schema_valid: bool
    fields: Optional[list[str]] = None
    table: Optional[str] = None
    chain: Optional[list[str | int]] = None


type DatabaseSchemaTable = (
    DatabaseSchemaPostHogTable
    | DatabaseSchemaSystemTable
    | DatabaseSchemaDataWarehouseTable
    | DatabaseSchemaViewTable
    | DatabaseSchemaManagedViewTable
)


class Database(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Users can query from the tables below
    tables: TableNode = TableNode(
        children={
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
            "log_entries": TableNode(name="log_entries", table=LogEntriesTable()),
            "query_log": TableNode(name="query_log", table=QueryLogArchiveTable()),
            "app_metrics": TableNode(name="app_metrics", table=AppMetrics2Table()),
            "console_logs_log_entries": TableNode(
                name="console_logs_log_entries", table=ReplayConsoleLogsLogEntriesTable()
            ),
            "batch_export_log_entries": TableNode(name="batch_export_log_entries", table=BatchExportLogEntriesTable()),
            "sessions": TableNode(name="sessions", table=SessionsTableV1()),
            "heatmaps": TableNode(name="heatmaps", table=HeatmapsTable()),
            "exchange_rate": TableNode(name="exchange_rate", table=ExchangeRateTable()),
            "document_embeddings": TableNode(name="document_embeddings", table=DocumentEmbeddingsTable()),
            "pg_embeddings": TableNode(name="pg_embeddings", table=PgEmbeddingsTable()),
            "logs": TableNode(name="logs", table=LogsTable()),
            "numbers": TableNode(name="numbers", table=NumbersTable()),
            "system": SystemTables(),  # This is a `TableNode` already, refer to implementation
            # Web analytics pre-aggregated tables (internal use only)
            "web_stats_daily": TableNode(name="web_stats_daily", table=WebStatsDailyTable()),
            "web_bounces_daily": TableNode(name="web_bounces_daily", table=WebBouncesDailyTable()),
            "web_stats_hourly": TableNode(name="web_stats_hourly", table=WebStatsHourlyTable()),
            "web_bounces_hourly": TableNode(name="web_bounces_hourly", table=WebBouncesHourlyTable()),
            "web_stats_combined": TableNode(name="web_stats_combined", table=WebStatsCombinedTable()),
            "web_bounces_combined": TableNode(name="web_bounces_combined", table=WebBouncesCombinedTable()),
            # V2 Pre-aggregated tables (will replace the above tables after we backfill)
            "web_pre_aggregated_stats": TableNode(name="web_pre_aggregated_stats", table=WebPreAggregatedStatsTable()),
            "web_pre_aggregated_bounces": TableNode(
                name="web_pre_aggregated_bounces", table=WebPreAggregatedBouncesTable()
            ),
            # Revenue analytics tables
            "persons_revenue_analytics": TableNode(
                name="persons_revenue_analytics", table=PersonsRevenueAnalyticsTable()
            ),
            "groups_revenue_analytics": TableNode(name="groups_revenue_analytics", table=GroupsRevenueAnalyticsTable()),
            # Raw tables used to support the streamlined tables above
            "raw_session_replay_events": TableNode(
                name="raw_session_replay_events", table=RawSessionReplayEventsTable()
            ),
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
            "raw_sessions": TableNode(name="raw_sessions", table=RawSessionsTableV1()),
            "raw_sessions_v3": TableNode(name="raw_sessions_v3", table=RawSessionsTableV3()),
            "raw_query_log": TableNode(name="raw_query_log", table=RawQueryLogArchiveTable()),
            "raw_document_embeddings": TableNode(name="raw_document_embeddings", table=RawDocumentEmbeddingsTable()),
        },
    )

    _warehouse_table_names: list[str] = []
    _warehouse_self_managed_table_names: list[str] = []
    _view_table_names: list[str] = []

    _timezone: Optional[str]
    _week_start_day: Optional[WeekStartDay]

    def __init__(self, timezone: Optional[str] = None, week_start_day: Optional[WeekStartDay] = None):
        super().__init__()
        try:
            self._timezone = str(ZoneInfo(timezone)) if timezone else None
        except ZoneInfoNotFoundError:
            raise ValueError(f"Unknown timezone: '{str(timezone)}'")

        self._week_start_day = week_start_day

    def get_timezone(self) -> str:
        return self._timezone or "UTC"

    def get_week_start_day(self) -> WeekStartDay:
        return self._week_start_day or WeekStartDay.SUNDAY

    def has_table(self, table_name: str | list[str]) -> bool:
        if isinstance(table_name, str):
            table_name = table_name.split(".")
        return self.tables.has_child(table_name)

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
            raise QueryError(f"Unknown table `{table_name}`.") from e

    def get_all_table_names(self) -> list[str]:
        warehouse_table_names = list(filter(lambda x: "." in x, self._warehouse_table_names))

        return (
            self.get_posthog_table_names()
            + warehouse_table_names
            + self._warehouse_self_managed_table_names
            + self._view_table_names
        )

    # These are the tables exposed via SQL editor autocomplete and data management
    def get_posthog_table_names(self) -> list[str]:
        return [
            "events",
            "groups",
            "persons",
            "sessions",
            *self.get_system_table_names(),
        ]

    def get_system_table_names(self) -> list[str]:
        return ["query_log", *cast(SystemTables, self.tables.children["system"]).resolve_all_table_names()]

    def get_warehouse_table_names(self) -> list[str]:
        return self._warehouse_table_names + self._warehouse_self_managed_table_names

    def get_view_names(self) -> list[str]:
        return self._view_table_names

    def _add_warehouse_tables(self, node: TableNode):
        self.tables.merge_with(node)
        for name in node.resolve_all_table_names():
            self._warehouse_table_names.append(name)

    def _add_warehouse_self_managed_tables(self, node: TableNode):
        self.tables.merge_with(node)
        for name in node.resolve_all_table_names():
            self._warehouse_self_managed_table_names.append(name)

    def _add_views(self, node: TableNode):
        self.tables.merge_with(node)
        for name in node.resolve_all_table_names():
            self._view_table_names.append(name)

    def serialize(
        self,
        context: HogQLContext,
        include_only: Optional[set[str]] = None,
    ) -> dict[str, DatabaseSchemaTable]:
        from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
        from products.revenue_analytics.backend.views import RevenueAnalyticsBaseView

        tables: dict[str, DatabaseSchemaTable] = {}

        if context.team_id is None:
            raise ResolutionError("Must provide team_id to serialize database")

        # PostHog tables
        posthog_table_names = self.get_posthog_table_names()
        for table_name in posthog_table_names:
            if include_only and table_name not in include_only:
                continue

            field_input: dict[str, Any] = {}
            table = self.get_table(table_name)
            if isinstance(table, FunctionCallTable):
                field_input = table.get_asterisk()
            elif isinstance(table, Table):
                field_input = table.fields

            fields = serialize_fields(field_input, context, table_name.split("."), table_type="posthog")
            fields_dict = {field.name: field for field in fields}
            tables[table_name] = DatabaseSchemaPostHogTable(fields=fields_dict, id=table_name, name=table_name)

        # System tables
        system_tables = self.get_system_table_names()
        for table_key in system_tables:
            if include_only and table_key not in include_only:
                continue

            system_field_input: dict[str, Any] = {}
            table = self.get_table(table_key)
            if isinstance(table, FunctionCallTable):
                system_field_input = table.get_asterisk()
            elif isinstance(table, Table):
                system_field_input = table.fields

            fields = serialize_fields(system_field_input, context, table_key.split("."), table_type="posthog")
            fields_dict = {field.name: field for field in fields}
            tables[table_key] = DatabaseSchemaSystemTable(fields=fields_dict, id=table_key, name=table_key)

        # Data Warehouse Tables and Views - Fetch all related data in one go
        warehouse_table_names = self.get_warehouse_table_names()
        views = self.get_view_names()

        # Fetch warehouse tables with related data in a single query
        warehouse_tables_with_data = (
            DataWarehouseTable.objects.select_related("credential", "external_data_source")
            .prefetch_related(
                "externaldataschema_set",
                Prefetch(
                    "external_data_source__jobs",
                    queryset=ExternalDataJob.objects.filter(status="Completed", team_id=context.team_id).order_by(
                        "-created_at"
                    )[:1],
                    to_attr="latest_completed_job",
                ),
            )
            .filter(Q(deleted=False) | Q(deleted__isnull=True), team_id=context.team_id, name__in=warehouse_table_names)
            .order_by("external_data_source__prefix", "external_data_source__source_type", "name")
            .all()
            if warehouse_table_names
            else []
        )

        # Process warehouse tables
        for warehouse_table in warehouse_tables_with_data:
            # Get schema from prefetched data
            schema_data = list(warehouse_table.externaldataschema_set.all())
            if not schema_data:
                schema = None
            else:
                db_schema = schema_data[0]
                schema = DatabaseSchemaSchema(
                    id=str(db_schema.id),
                    name=db_schema.name,
                    should_sync=db_schema.should_sync,
                    incremental=db_schema.is_incremental,
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
                    id=str(db_source.source_id),
                    status=db_source.status,
                    source_type=db_source.source_type,
                    prefix=db_source.prefix or "",
                    last_synced_at=str(latest_completed_run.created_at) if latest_completed_run else None,
                )

            # Temp until we migrate all table names in the DB to use dot notation
            if warehouse_table.external_data_source:
                source_type = warehouse_table.external_data_source.source_type
                prefix = warehouse_table.external_data_source.prefix
                if prefix is not None and isinstance(prefix, str) and prefix != "":
                    table_name_stripped = warehouse_table.name.replace(f"{prefix}{source_type}_".lower(), "")
                    table_key = f"{source_type}.{prefix.strip('_')}.{table_name_stripped}".lower()
                else:
                    table_name_stripped = warehouse_table.name.replace(f"{source_type}_".lower(), "")
                    table_key = f"{source_type}.{table_name_stripped}".lower()
            else:
                table_key = warehouse_table.name

            if include_only and table_key not in include_only:
                continue

            field_input = {}
            table = self.get_table(table_key)
            if isinstance(table, Table):
                field_input = table.fields

            fields = serialize_fields(
                field_input, context, table_key.split("."), warehouse_table.columns, table_type="external"
            )
            fields_dict = {field.name: field for field in fields}

            tables[table_key] = DatabaseSchemaDataWarehouseTable(
                fields=fields_dict,
                id=str(warehouse_table.id),
                name=table_key,
                format=warehouse_table.format,
                url_pattern=warehouse_table.url_pattern,
                schema=schema,
                source=source,
                row_count=warehouse_table.row_count,
            )

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

            tables[view_name] = DatabaseSchemaViewTable(
                fields=fields_dict,
                id=str(saved_query.pk),
                name=view_name,
                query=HogQLQuery(query=saved_query.query["query"]),
                row_count=row_count,
            )

        return tables

    @staticmethod
    @tracer.start_as_current_span("create_hogql_database")  # Legacy name to keep backwards compatibility
    def create_for(
        team_id: Optional[int] = None,
        *,
        team: Optional["Team"] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        timings: Optional[HogQLTimings] = None,
    ) -> "Database":
        from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable
        from posthog.hogql.query import create_default_modifiers_for_team

        from posthog.models import Team

        from products.data_warehouse.backend.models import DataWarehouseJoin, DataWarehouseSavedQuery

        if timings is None:
            timings = HogQLTimings()

        with timings.measure("team"):
            if team_id is None and team is None:
                raise ValueError("Either team_id or team must be provided")

            if team is not None and team_id is not None and team.pk != team_id:
                raise ValueError("team_id and team must be the same")

            if team is None:
                team = Team.objects.get(pk=team_id)

            # Team is definitely not None at this point, make mypy believe that
            team = cast("Team", team)

            # Set team_id for the create_hogql_database tracing span
            span = trace.get_current_span()
            span.set_attribute("team_id", team.pk)

        with timings.measure("database"):
            database = Database(timezone=team.timezone, week_start_day=team.week_start_day)

        with timings.measure("modifiers"):
            modifiers = create_default_modifiers_for_team(team, modifiers)

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
                    join_function=join_with_persons_table,
                )

            _use_error_tracking_issue_id_from_error_tracking_issue_overrides(database)

        with timings.measure("session_table"):
            if (
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
                    join_function=join_events_table_to_sessions_table_v2,
                )

                replay_events = database.get_table("session_replay_events")
                replay_events.fields["session"] = LazyJoin(
                    from_field=["session_id"],
                    join_table=sessions,
                    join_function=join_replay_table_to_sessions_table_v2,
                )
                cast(LazyJoin, replay_events.fields["events"]).join_table = events_table

                raw_replay_events = database.get_table("raw_session_replay_events")
                raw_replay_events.fields["session"] = LazyJoin(
                    from_field=["session_id"],
                    join_table=sessions,
                    join_function=join_replay_table_to_sessions_table_v2,
                )
                cast(LazyJoin, raw_replay_events.fields["events"]).join_table = events_table
            elif modifiers.sessionTableVersion == SessionTableVersion.V3:
                sessions = SessionsTableV3()
                database.tables.add_child(TableNode(name="sessions", table=sessions), table_conflict_mode="override")

                events_table = database.get_table("events")
                events_table.fields["session"] = LazyJoin(
                    from_field=["$session_id"],
                    join_table=sessions,
                    join_function=join_events_table_to_sessions_table_v3,
                )

                replay_events = database.get_table("session_replay_events")
                replay_events.fields["session"] = LazyJoin(
                    from_field=["session_id"],
                    join_table=sessions,
                    join_function=join_replay_table_to_sessions_table_v3,
                )
                cast(LazyJoin, replay_events.fields["events"]).join_table = events_table

                raw_replay_events = database.get_table("raw_session_replay_events")
                raw_replay_events.fields["session"] = LazyJoin(
                    from_field=["session_id"],
                    join_table=sessions,
                    join_function=join_replay_table_to_sessions_table_v3,
                )
                cast(LazyJoin, raw_replay_events.fields["events"]).join_table = events_table

        with timings.measure("virtual_fields"):
            _use_virtual_fields(database, modifiers, timings)

        with timings.measure("group_type_mapping"):
            _setup_group_key_fields(database, team)
            events_table = database.get_table("events")
            for mapping in GroupTypeMapping.objects.filter(project_id=team.project_id):
                if events_table.fields.get(mapping.group_type) is None:
                    events_table.fields[mapping.group_type] = FieldTraverser(
                        chain=[f"group_{mapping.group_type_index}"]
                    )

        warehouse_tables_dot_notation_mapping: dict[str, str] = {}
        warehouse_tables: TableNode = TableNode()
        self_managed_warehouse_tables: TableNode = TableNode()
        views: TableNode = TableNode()

        with timings.measure("data_warehouse_saved_query"):
            with timings.measure("select"):
                saved_queries = list(
                    DataWarehouseSavedQuery.objects.filter(team_id=team.pk)
                    .filter(managed_viewset__isnull=True)  # Ignore managed views for now
                    .exclude(deleted=True)
                    .select_related("table", "table__credential")
                )

            for saved_query in saved_queries:
                with timings.measure(f"saved_query_{saved_query.name}"):
                    views.add_child(
                        TableNode(name=saved_query.name, table=saved_query.hogql_definition(modifiers)),
                        table_conflict_mode="ignore",
                    )

        with timings.measure("revenue_analytics_views"):
            revenue_views = []
            try:
                revenue_views = list(build_all_revenue_analytics_views(team, timings))
            except Exception as e:
                capture_exception(e)

            # Each view will have a name similar to `stripe.<prefix>.<table_name>`
            # We want to create a nested table group where `stripe` is the parent,
            # `<prefix>` is the child of `stripe`, and `<table_name>` is the child of `<prefix>`
            # allowing you to access the table as `stripe[prefix][table_name]` in a dict fashion
            # but still allowing the bare `stripe.prefix.table_name` string access
            for view in revenue_views:
                try:
                    views.add_child(TableNode.create_nested_for_chain(view.name.split("."), view))
                except Exception as e:
                    capture_exception(e)
                    continue

        with timings.measure("data_warehouse_tables"):

            class WarehousePropertiesVirtualTable(VirtualTable):
                fields: dict[str, FieldOrTable]
                parent_table: HogQLDataWarehouseTable

                def to_printed_hogql(self):
                    return self.parent_table.to_printed_hogql()

                def to_printed_clickhouse(self, context):
                    return self.parent_table.to_printed_clickhouse(context)

            with timings.measure("select"):
                tables: list[DataWarehouseTable] = list(
                    DataWarehouseTable.raw_objects.filter(team_id=team.pk)
                    .exclude(deleted=True)
                    .select_related("credential", "external_data_source")
                )

            view_names = views.resolve_all_table_names()
            for table in tables:
                # Skip adding data warehouse tables that are materialized from views
                # We can detect that because they have the exact same name as the view
                if table.name in view_names:
                    continue

                with timings.measure(f"table_{table.name}"):
                    s3_table = table.hogql_definition(modifiers)

                    # If the warehouse table has no _properties_ field, then set it as a virtual table
                    if s3_table.fields.get("properties") is None:
                        s3_table.fields["properties"] = WarehousePropertiesVirtualTable(
                            fields=s3_table.fields, parent_table=s3_table, hidden=True
                        )

                    if table.external_data_source:
                        warehouse_tables.add_child(TableNode(name=table.name, table=s3_table))
                    else:
                        self_managed_warehouse_tables.add_child(TableNode(name=table.name, table=s3_table))

                    # Add warehouse table using dot notation
                    if table.external_data_source:
                        source_type = table.external_data_source.source_type
                        prefix = table.external_data_source.prefix
                        table_chain: list[str] = [source_type.lower()]

                        if prefix is not None and isinstance(prefix, str) and prefix != "":
                            table_name_stripped = table.name.replace(f"{prefix}{source_type}_".lower(), "")
                            table_chain.extend([prefix.strip("_").lower(), table_name_stripped])
                        else:
                            table_name_stripped = table.name.replace(f"{source_type}_".lower(), "")
                            table_chain.append(table_name_stripped)

                        # For a chain of type a.b.c, we want to create a nested table node
                        # where a is the parent, b is the child of a, and c is the child of b
                        # where a.b.c will contain the s3_table
                        warehouse_tables.add_child(TableNode.create_nested_for_chain(table_chain, s3_table))

                        joined_table_chain = ".".join(table_chain)
                        s3_table.name = joined_table_chain
                        warehouse_tables_dot_notation_mapping[joined_table_chain] = table.name

        def define_mappings(root_node: TableNode, get_table: Callable):
            table: Table | None = None

            if root_node.has_child([warehouse_modifier.table_name]):
                _table = root_node.get_child([warehouse_modifier.table_name]).get()
                assert isinstance(_table, Table)

                table = _table

            if "." in warehouse_modifier.table_name:
                table_chain = warehouse_modifier.table_name.split(".")
                if table_chain[0] not in root_node.children:
                    return root_node

                _table = root_node.get_child(table_chain).get()
                assert isinstance(_table, Table)

                table = _table

            if table is None:
                return root_node

            if "id" not in table.fields.keys():
                table.fields["id"] = ExpressionField(
                    name="id",
                    expr=parse_expr(warehouse_modifier.id_field),
                )

            table_has_no_timestamp_field = "timestamp" not in table.fields.keys()
            timestamp_field_is_datetime = isinstance(table.fields.get("timestamp"), DateTimeDatabaseField)

            if table_has_no_timestamp_field or not timestamp_field_is_datetime:
                table_model = get_table(team=team, warehouse_modifier=warehouse_modifier)
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

            # TODO: Need to decide how the distinct_id and person_id fields are going to be handled
            if "distinct_id" not in table.fields.keys():
                table.fields["distinct_id"] = ExpressionField(
                    name="distinct_id",
                    expr=parse_expr(warehouse_modifier.distinct_id_field),
                )

            if "person_id" not in table.fields.keys():
                events_join = (
                    DataWarehouseJoin.objects.filter(
                        team_id=team.pk,
                        source_table_name=warehouse_modifier.table_name,
                        joining_table_name="events",
                    )
                    .exclude(deleted=True)
                    .first()
                )
                if events_join:
                    table.fields["person_id"] = FieldTraverser(chain=[events_join.field_name, "person_id"])
                else:
                    table.fields["person_id"] = ExpressionField(
                        name="person_id",
                        expr=parse_expr(warehouse_modifier.distinct_id_field),
                    )

            return root_node

        if modifiers.dataWarehouseEventsModifiers:
            with timings.measure("data_warehouse_event_modifiers"):
                for warehouse_modifier in modifiers.dataWarehouseEventsModifiers:
                    with timings.measure(f"data_warehouse_event_modifier_{warehouse_modifier.table_name}"):
                        # TODO: add all field mappings
                        is_view = views.has_child([warehouse_modifier.table_name])

                        if is_view:
                            views = define_mappings(
                                views,
                                lambda team, warehouse_modifier: DataWarehouseSavedQuery.objects.exclude(deleted=True)
                                .filter(team_id=team.pk, name=warehouse_modifier.table_name)
                                .latest("created_at"),
                            )
                        else:
                            warehouse_tables = define_mappings(
                                warehouse_tables,
                                lambda team, warehouse_modifier: DataWarehouseTable.objects.exclude(deleted=True)
                                .filter(
                                    team_id=team.pk,
                                    name=warehouse_tables_dot_notation_mapping[warehouse_modifier.table_name]
                                    if warehouse_modifier.table_name in warehouse_tables_dot_notation_mapping
                                    else warehouse_modifier.table_name,
                                )
                                .select_related("credential", "external_data_source")
                                .latest("created_at"),
                            )
                            self_managed_warehouse_tables = define_mappings(
                                self_managed_warehouse_tables,
                                lambda team, warehouse_modifier: DataWarehouseTable.objects.exclude(deleted=True)
                                .filter(team_id=team.pk, name=warehouse_modifier.table_name)
                                .select_related("credential", "external_data_source")
                                .latest("created_at"),
                            )

        database._add_warehouse_tables(warehouse_tables)
        database._add_warehouse_self_managed_tables(self_managed_warehouse_tables)
        database._add_views(views)

        with timings.measure("data_warehouse_joins"):
            for join in DataWarehouseJoin.objects.filter(team_id=team.pk).exclude(deleted=True):
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

                    source_table.fields[join.field_name] = LazyJoin(
                        from_field=from_field,
                        to_field=to_field,
                        join_table=joining_table,
                        join_function=(
                            join.join_function_for_experiments()
                            if "events" == join.joining_table_name and join.configuration.get("experiments_optimized")
                            else join.join_function()
                        ),
                    )

                    if join.source_table_name == "persons":
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

                                # If the source_table_key is a ast.Call node, then we want to inject in `person` on the chain of the inner `ast.Field` node
                                source_table_key_node = parse_expr(join.source_table_key)
                                if isinstance(source_table_key_node, ast.Call) and isinstance(
                                    source_table_key_node.args[0], ast.Field
                                ):
                                    source_table_key_node.args[0].chain = [
                                        "person",
                                        *source_table_key_node.args[0].chain,
                                    ]
                                    override_source_table_key = source_table_key_node.to_hogql()

                                events_table.fields[join.field_name] = LazyJoin(
                                    from_field=from_field,
                                    to_field=to_field,
                                    join_table=joining_table,
                                    # reusing join_function but with different source_table_key since we're joining 'directly' on events
                                    join_function=join.join_function(
                                        override_source_table_key=override_source_table_key
                                    ),
                                )
                            else:
                                table_or_field.fields[join.field_name] = LazyJoin(
                                    from_field=from_field,
                                    to_field=to_field,
                                    join_table=joining_table,
                                    join_function=join.join_function(),
                                )
                        elif isinstance(person_field, ast.LazyJoin):
                            person_field.join_table.fields[join.field_name] = LazyJoin(  # type: ignore
                                from_field=from_field,
                                to_field=to_field,
                                join_table=joining_table,
                                join_function=join.join_function(),
                            )

                except Exception as e:
                    capture_exception(e)

        return database


def _use_person_properties_from_events(database: Database) -> None:
    database.get_table("events").fields["person"] = FieldTraverser(chain=["poe"])


def _use_person_id_from_person_overrides(database: Database) -> None:
    table = database.get_table("events")
    table.fields["event_person_id"] = StringDatabaseField(name="person_id")
    table.fields["override"] = LazyJoin(
        from_field=["distinct_id"],
        join_table=database.get_table("person_distinct_id_overrides"),
        join_function=join_with_person_distinct_id_overrides_table,
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


def _use_error_tracking_issue_id_from_error_tracking_issue_overrides(database: Database) -> None:
    table = database.get_table("events")
    table.fields["event_issue_id"] = ExpressionField(
        name="event_issue_id",
        # convert to UUID to match type of `issue_id` on overrides table
        expr=parse_expr("toUUID(properties.$exception_issue_id)"),
    )
    table.fields["exception_issue_override"] = LazyJoin(
        from_field=["fingerprint"],
        join_table=ErrorTrackingIssueFingerprintOverridesTable(),
        join_function=join_with_error_tracking_issue_fingerprint_overrides_table,
    )
    table.fields["issue_id"] = ExpressionField(
        name="issue_id",
        expr=parse_expr(
            # NOTE: assumes `join_use_nulls = 0` (the default), as ``override.fingerprint`` is not Nullable
            "if(not(empty(exception_issue_override.issue_id)), exception_issue_override.issue_id, event_issue_id)",
            start=None,
        ),
    )


def _setup_group_key_fields(database: Database, team: "Team") -> None:
    """
    Set up group key fields as ExpressionFields that handle filtering based on GroupTypeMapping.created_at.
    For $group_N fields, this returns:
    - Empty string if no GroupTypeMapping exists for that index
    - if(timestamp < mapping.created_at, '', $group_N) if GroupTypeMapping exists
    """
    group_mappings = {mapping.group_type_index: mapping for mapping in GroupTypeMapping.objects.filter(team=team)}
    table = database.get_table("events")

    for group_index in range(5):
        field_name = f"$group_{group_index}"

        group_mapping = group_mappings.get(group_index, None)
        # If no mapping exists or the mapping predated this feature, leave the original field unchanged
        if group_mapping and group_mapping.created_at:
            # Store the original field as a "raw" version before replacing
            original_field = table.fields[field_name]
            raw_field_name = f"_{field_name}_raw"
            table.fields[raw_field_name] = original_field.model_copy(update={"hidden": True})

            created_at_str = group_mapping.created_at.strftime("%Y-%m-%d %H:%M:%S")

            table.fields[field_name] = ExpressionField(
                name=field_name,
                expr=ast.Call(
                    name="if",
                    args=[
                        ast.CompareOperation(
                            left=ast.Field(chain=["timestamp"]),
                            op=ast.CompareOperationOp.Lt,
                            right=ast.Constant(value=created_at_str),
                        ),
                        ast.Constant(value=""),
                        ast.Field(chain=[raw_field_name]),
                    ],
                ),
                isolate_scope=True,
            )


def _use_virtual_fields(database: Database, modifiers: HogQLQueryModifiers, timings: HogQLTimings) -> None:
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

    # :KLUDGE: Currently calculated at runtime via the `revenue_analytics` table,
    # it'd be wise to make these computable fields in the future, but that's a big uplift
    revenue_fields = ["revenue", "revenue_last_30_days"]
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


def serialize_fields(
    field_input,
    context: HogQLContext,
    table_chain: list[str],
    db_columns: Optional[DataWarehouseTableColumns] = None,
    table_type: Literal["posthog"] | Literal["external"] = "posthog",
) -> list[DatabaseSchemaField]:
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
