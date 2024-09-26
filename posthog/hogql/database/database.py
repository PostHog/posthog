import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Optional, TypeAlias, cast, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Q
from pydantic import ConfigDict, BaseModel
from sentry_sdk import capture_exception

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    FieldOrTable,
    FieldTraverser,
    SavedQuery,
    StringDatabaseField,
    DatabaseField,
    IntegerDatabaseField,
    DateTimeDatabaseField,
    BooleanDatabaseField,
    StringJSONDatabaseField,
    StringArrayDatabaseField,
    LazyJoin,
    VirtualTable,
    Table,
    DateDatabaseField,
    FloatDatabaseField,
    FunctionCallTable,
    ExpressionField,
)
from posthog.hogql.database.schema.channel_type import create_initial_channel_type, create_initial_domain_type
from posthog.hogql.database.schema.cohort_people import CohortPeople, RawCohortPeople
from posthog.hogql.database.schema.events import EventsTable, EventsLazy
from posthog.hogql.database.schema.groups import GroupsTable, RawGroupsTable
from posthog.hogql.database.schema.heatmaps import HeatmapsTable
from posthog.hogql.database.schema.log_entries import (
    LogEntriesTable,
    ReplayConsoleLogsLogEntriesTable,
    BatchExportLogEntriesTable,
)
from posthog.hogql.database.schema.numbers import NumbersTable
from posthog.hogql.database.schema.person_distinct_id_overrides import (
    PersonDistinctIdOverridesTable,
    RawPersonDistinctIdOverridesTable,
    join_with_person_distinct_id_overrides_table,
)
from posthog.hogql.database.schema.person_distinct_ids import (
    PersonDistinctIdsTable,
    RawPersonDistinctIdsTable,
)
from posthog.hogql.database.schema.persons import (
    PersonsTable,
    RawPersonsTable,
    join_with_persons_table,
)
from posthog.hogql.database.schema.session_replay_events import (
    RawSessionReplayEventsTable,
    SessionReplayEventsTable,
    join_replay_table_to_sessions_table_v2,
)
from posthog.hogql.database.schema.sessions_v1 import RawSessionsTableV1, SessionsTableV1
from posthog.hogql.database.schema.sessions_v2 import (
    SessionsTableV2,
    RawSessionsTableV2,
    join_events_table_to_sessions_table_v2,
)
from posthog.hogql.database.schema.static_cohort_people import StaticCohortPeople
from posthog.hogql.errors import QueryError, ResolutionError
from posthog.hogql.parser import parse_expr
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.team.team import WeekStartDay
from posthog.schema import (
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaField,
    DatabaseSchemaPostHogTable,
    DatabaseSchemaSchema,
    DatabaseSchemaSource,
    DatabaseSchemaViewTable,
    DatabaseSerializedFieldType,
    HogQLQuery,
    HogQLQueryModifiers,
    PersonsOnEventsMode,
    SessionTableVersion,
)
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import (
    DataWarehouseTable,
    DataWarehouseTableColumns,
)

if TYPE_CHECKING:
    from posthog.models import Team


class Database(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Users can query from the tables below
    # events: EventsTable = EventsTable()
    groups: GroupsTable = GroupsTable()
    persons: PersonsTable = PersonsTable()
    person_distinct_ids: PersonDistinctIdsTable = PersonDistinctIdsTable()
    person_distinct_id_overrides: PersonDistinctIdOverridesTable = PersonDistinctIdOverridesTable()

    session_replay_events: SessionReplayEventsTable = SessionReplayEventsTable()
    cohort_people: CohortPeople = CohortPeople()
    static_cohort_people: StaticCohortPeople = StaticCohortPeople()
    log_entries: LogEntriesTable = LogEntriesTable()
    console_logs_log_entries: ReplayConsoleLogsLogEntriesTable = ReplayConsoleLogsLogEntriesTable()
    batch_export_log_entries: BatchExportLogEntriesTable = BatchExportLogEntriesTable()
    sessions: Union[SessionsTableV1, SessionsTableV2] = SessionsTableV1()
    heatmaps: HeatmapsTable = HeatmapsTable()

    raw_session_replay_events: RawSessionReplayEventsTable = RawSessionReplayEventsTable()
    raw_person_distinct_ids: RawPersonDistinctIdsTable = RawPersonDistinctIdsTable()
    raw_persons: RawPersonsTable = RawPersonsTable()
    raw_groups: RawGroupsTable = RawGroupsTable()
    raw_cohort_people: RawCohortPeople = RawCohortPeople()
    raw_person_distinct_id_overrides: RawPersonDistinctIdOverridesTable = RawPersonDistinctIdOverridesTable()
    raw_sessions: Union[RawSessionsTableV1, RawSessionsTableV2] = RawSessionsTableV1()

    events_lazy: EventsLazy = EventsLazy()
    events: EventsTable = EventsTable()

    # system tables
    numbers: NumbersTable = NumbersTable()

    # These are the tables exposed via SQL editor autocomplete and data management
    _table_names: ClassVar[list[str]] = [
        "events",
        "groups",
        "persons",
        "person_distinct_ids",
        "session_replay_events",
        "cohort_people",
        "static_cohort_people",
        "log_entries",
        "sessions",
        "heatmaps",
    ]

    _warehouse_table_names: list[str] = []
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

    def has_table(self, table_name: str) -> bool:
        return hasattr(self, table_name)

    def get_table(self, table_name: str) -> Table:
        if self.has_table(table_name):
            return getattr(self, table_name)
        raise QueryError(f'Unknown table "{table_name}".')

    def get_all_tables(self) -> list[str]:
        return self._table_names + self._warehouse_table_names

    def get_posthog_tables(self) -> list[str]:
        return self._table_names

    def get_warehouse_tables(self) -> list[str]:
        return self._warehouse_table_names

    def get_views(self) -> list[str]:
        return self._view_table_names

    def add_warehouse_tables(self, **field_definitions: Any):
        for f_name, f_def in field_definitions.items():
            setattr(self, f_name, f_def)
            self._warehouse_table_names.append(f_name)

    def add_views(self, **field_definitions: Any):
        for f_name, f_def in field_definitions.items():
            setattr(self, f_name, f_def)
            self._view_table_names.append(f_name)


def _use_person_properties_from_events(database: Database) -> None:
    for table in (database.events_lazy,):  # database.events,
        table.fields["person"] = FieldTraverser(chain=["poe"])
        table.fields["person"] = FieldTraverser(chain=["poe"])


def _use_person_id_from_person_overrides(database: Database) -> None:
    for table in (database.events_lazy,):  # database.events,
        table.fields["event_person_id"] = StringDatabaseField(name="person_id")
        table.fields["override"] = LazyJoin(
            from_field=["distinct_id"],
            join_table=PersonDistinctIdOverridesTable(),
            join_function=join_with_person_distinct_id_overrides_table,
        )
        table.fields["person_id"] = ExpressionField(
            name="person_id",
            expr=parse_expr(
                # NOTE: assumes `join_use_nulls = 0` (the default), as ``override.distinct_id`` is not Nullable
                "if(not(empty(override.distinct_id)), override.person_id, event_person_id)",
                start=None,
            ),
        )


def create_hogql_database(
    team_id: int, modifiers: Optional[HogQLQueryModifiers] = None, team_arg: Optional["Team"] = None
) -> Database:
    from posthog.models import Team
    from posthog.hogql.database.s3_table import S3Table
    from posthog.hogql.query import create_default_modifiers_for_team
    from posthog.warehouse.models import (
        DataWarehouseTable,
        DataWarehouseSavedQuery,
        DataWarehouseJoin,
    )

    team = team_arg or Team.objects.get(pk=team_id)
    modifiers = create_default_modifiers_for_team(team, modifiers)
    database = Database(timezone=team.timezone, week_start_day=team.week_start_day)

    # can add events back here for normal behavior
    for table in (database.events_lazy,):
        if modifiers.personsOnEventsMode == PersonsOnEventsMode.DISABLED:
            # no change
            table.fields["person"] = FieldTraverser(chain=["pdi", "person"])
            table.fields["person_id"] = FieldTraverser(chain=["pdi", "person_id"])

        elif modifiers.personsOnEventsMode == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS:
            table.fields["person_id"] = StringDatabaseField(name="person_id")
            _use_person_properties_from_events(database)

        elif modifiers.personsOnEventsMode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS:
            _use_person_id_from_person_overrides(database)
            _use_person_properties_from_events(database)
            table.fields["poe"].fields["id"] = table.fields["person_id"]

        elif modifiers.personsOnEventsMode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED:
            _use_person_id_from_person_overrides(database)
            table.fields["person"] = LazyJoin(
                from_field=["person_id"],
                join_table=PersonsTable(),
                join_function=join_with_persons_table,
            )

    if (
        modifiers.sessionTableVersion == SessionTableVersion.V2
        or modifiers.sessionTableVersion == SessionTableVersion.AUTO
    ):
        raw_sessions = RawSessionsTableV2()
        database.raw_sessions = raw_sessions
        sessions = SessionsTableV2()
        database.sessions = sessions
        events = database.events
        events.fields["session"] = LazyJoin(
            from_field=["$session_id"],
            join_table=sessions,
            join_function=join_events_table_to_sessions_table_v2,
        )
        replay_events = database.session_replay_events
        replay_events.fields["session"] = LazyJoin(
            from_field=["session_id"],
            join_table=sessions,
            join_function=join_replay_table_to_sessions_table_v2,
        )
        replay_events.fields["events"].join_table = events
        raw_replay_events = database.raw_session_replay_events
        raw_replay_events.fields["session"] = LazyJoin(
            from_field=["session_id"],
            join_table=sessions,
            join_function=join_replay_table_to_sessions_table_v2,
        )
        raw_replay_events.fields["events"].join_table = events

    database.persons.fields["$virt_initial_referring_domain_type"] = create_initial_domain_type(
        "$virt_initial_referring_domain_type"
    )
    database.persons.fields["$virt_initial_channel_type"] = create_initial_channel_type("$virt_initial_channel_type")

    for mapping in GroupTypeMapping.objects.filter(team=team):
        if database.events.fields.get(mapping.group_type) is None:
            database.events.fields[mapping.group_type] = FieldTraverser(chain=[f"group_{mapping.group_type_index}"])

    warehouse_tables: dict[str, Table] = {}
    views: dict[str, Table] = {}

    for table in (
        DataWarehouseTable.objects.filter(team_id=team.pk)
        .exclude(deleted=True)
        .select_related("credential", "external_data_source")
    ):
        s3_table = table.hogql_definition(modifiers)

        # If the warehouse table has no _properties_ field, then set it as a virtual table
        if s3_table.fields.get("properties") is None:

            class WarehouseProperties(VirtualTable):
                fields: dict[str, FieldOrTable] = s3_table.fields
                parent_table: S3Table = s3_table

                def to_printed_hogql(self):
                    return self.parent_table.to_printed_hogql()

                def to_printed_clickhouse(self, context):
                    return self.parent_table.to_printed_clickhouse(context)

            s3_table.fields["properties"] = WarehouseProperties()

        warehouse_tables[table.name] = s3_table

    for saved_query in DataWarehouseSavedQuery.objects.filter(team_id=team.pk).exclude(deleted=True):
        views[saved_query.name] = saved_query.hogql_definition()

    def define_mappings(warehouse: dict[str, Table], get_table: Callable):
        if "id" not in warehouse[warehouse_modifier.table_name].fields.keys():
            warehouse[warehouse_modifier.table_name].fields["id"] = ExpressionField(
                name="id",
                expr=parse_expr(warehouse_modifier.id_field),
            )

        if "timestamp" not in warehouse[warehouse_modifier.table_name].fields.keys():
            table_model = get_table(team=team, warehouse_modifier=warehouse_modifier)
            timestamp_field_type = table_model.get_clickhouse_column_type(warehouse_modifier.timestamp_field)

            # If field type is none or datetime, we can use the field directly
            if timestamp_field_type is None or timestamp_field_type.startswith("DateTime"):
                warehouse[warehouse_modifier.table_name].fields["timestamp"] = ExpressionField(
                    name="timestamp",
                    expr=ast.Field(chain=[warehouse_modifier.timestamp_field]),
                )
            else:
                warehouse[warehouse_modifier.table_name].fields["timestamp"] = ExpressionField(
                    name="timestamp",
                    expr=ast.Call(name="toDateTime", args=[ast.Field(chain=[warehouse_modifier.timestamp_field])]),
                )

        # TODO: Need to decide how the distinct_id and person_id fields are going to be handled
        if "distinct_id" not in warehouse[warehouse_modifier.table_name].fields.keys():
            warehouse[warehouse_modifier.table_name].fields["distinct_id"] = ExpressionField(
                name="distinct_id",
                expr=parse_expr(warehouse_modifier.distinct_id_field),
            )

        if "person_id" not in warehouse[warehouse_modifier.table_name].fields.keys():
            warehouse[warehouse_modifier.table_name].fields["person_id"] = ExpressionField(
                name="person_id",
                expr=parse_expr(warehouse_modifier.distinct_id_field),
            )

        return warehouse

    if modifiers.dataWarehouseEventsModifiers:
        for warehouse_modifier in modifiers.dataWarehouseEventsModifiers:
            # TODO: add all field mappings

            is_view = warehouse_modifier.table_name in views.keys()

            if is_view:
                views = define_mappings(
                    views,
                    lambda team, warehouse_modifier: DataWarehouseSavedQuery.objects.filter(
                        team_id=team.pk, name=warehouse_modifier.table_name
                    ).latest("created_at"),
                )
            else:
                warehouse_tables = define_mappings(
                    warehouse_tables,
                    lambda team, warehouse_modifier: DataWarehouseTable.objects.exclude(deleted=True)
                    .filter(team_id=team.pk, name=warehouse_modifier.table_name)
                    .select_related("credential", "external_data_source")
                    .latest("created_at"),
                )

    database.add_warehouse_tables(**warehouse_tables)
    database.add_views(**views)

    for join in DataWarehouseJoin.objects.filter(team_id=team.pk).exclude(deleted=True):
        # Skip if either table is not present. This can happen if the table was deleted after the join was created.
        # User will be prompted on UI to resolve missing tables underlying the JOIN
        if not database.has_table(join.source_table_name) or not database.has_table(join.joining_table_name):
            continue

        try:
            source_table = database.get_table(join.source_table_name)
            joining_table = database.get_table(join.joining_table_name)

            field = parse_expr(join.source_table_key)
            if not isinstance(field, ast.Field):
                raise ResolutionError("Data Warehouse Join HogQL expression should be a Field node")
            from_field = field.chain

            field = parse_expr(join.joining_table_key)
            if not isinstance(field, ast.Field):
                raise ResolutionError("Data Warehouse Join HogQL expression should be a Field node")
            to_field = field.chain

            source_table.fields[join.field_name] = LazyJoin(
                from_field=from_field,
                to_field=to_field,
                join_table=joining_table,
                join_function=join.join_function(),
            )

            if join.source_table_name == "persons":
                person_field = database.events.fields["person"]
                if isinstance(person_field, ast.FieldTraverser):
                    table_or_field: ast.FieldOrTable = database.events
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
                        table_or_field.fields[join.field_name] = ast.FieldTraverser(chain=["..", join.field_name])
                        database.events.fields[join.field_name] = LazyJoin(
                            from_field=from_field,
                            to_field=to_field,
                            join_table=joining_table,
                            # reusing join_function but with different source_table_key since we're joining 'directly' on events
                            join_function=join.join_function(
                                override_source_table_key=f"person.{join.source_table_key}"
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


@dataclasses.dataclass
class SerializedField:
    key: str
    name: str
    type: DatabaseSerializedFieldType
    schema_valid: bool
    fields: Optional[list[str]] = None
    table: Optional[str] = None
    chain: Optional[list[str | int]] = None


DatabaseSchemaTable: TypeAlias = DatabaseSchemaPostHogTable | DatabaseSchemaDataWarehouseTable | DatabaseSchemaViewTable


def serialize_database(
    context: HogQLContext,
) -> dict[str, DatabaseSchemaTable]:
    from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery

    tables: dict[str, DatabaseSchemaTable] = {}

    if context.database is None:
        raise ResolutionError("Must provide database to serialize_database")

    if context.team_id is None:
        raise ResolutionError("Must provide team_id to serialize_database")

    # PostHog Tables
    posthog_tables = context.database.get_posthog_tables()
    for table_key in posthog_tables:
        field_input: dict[str, Any] = {}
        table = getattr(context.database, table_key, None)
        if isinstance(table, FunctionCallTable):
            field_input = table.get_asterisk()
        elif isinstance(table, Table):
            field_input = table.fields

        fields = serialize_fields(field_input, context, table_key, table_type="posthog")
        fields_dict = {field.name: field for field in fields}
        tables[table_key] = DatabaseSchemaPostHogTable(fields=fields_dict, id=table_key, name=table_key)

    # Data Warehouse Tables
    warehouse_table_names = context.database.get_warehouse_tables()
    warehouse_tables = (
        list(
            DataWarehouseTable.objects.select_related("credential", "external_data_source")
            .filter(Q(deleted=False) | Q(deleted__isnull=True), team_id=context.team_id, name__in=warehouse_table_names)
            .all()
        )
        if len(warehouse_table_names) > 0
        else []
    )
    warehouse_schemas = (
        list(
            ExternalDataSchema.objects.exclude(deleted=True)
            .filter(table_id__in=[table.id for table in warehouse_tables])
            .all()
        )
        if len(warehouse_tables) > 0
        else []
    )
    for warehouse_table in warehouse_tables:
        table_key = warehouse_table.name

        field_input = {}
        table = getattr(context.database, table_key, None)
        if isinstance(table, Table):
            field_input = table.fields

        fields = serialize_fields(field_input, context, table_key, warehouse_table.columns, table_type="external")
        fields_dict = {field.name: field for field in fields}

        # Schema
        schema_filter: list[ExternalDataSchema] = list(
            filter(lambda schema: schema.table_id == warehouse_table.id, warehouse_schemas)
        )
        if len(schema_filter) == 0:
            schema: DatabaseSchemaSchema | None = None
        else:
            db_schema = schema_filter[0]
            schema = DatabaseSchemaSchema(
                id=str(db_schema.id),
                name=db_schema.name,
                should_sync=db_schema.should_sync,
                incremental=db_schema.is_incremental,
                status=db_schema.status,
                last_synced_at=str(db_schema.last_synced_at),
            )

        # Source
        if warehouse_table.external_data_source is None:
            source: DatabaseSchemaSource | None = None
        else:
            db_source: ExternalDataSource = warehouse_table.external_data_source
            latest_completed_run = (
                ExternalDataJob.objects.filter(pipeline_id=db_source.pk, status="Completed", team_id=context.team_id)
                .order_by("-created_at")
                .first()
            )
            source = DatabaseSchemaSource(
                id=str(db_source.source_id),
                status=db_source.status,
                source_type=db_source.source_type,
                prefix=db_source.prefix or "",
                last_synced_at=str(latest_completed_run.created_at) if latest_completed_run else None,
            )

        tables[table_key] = DatabaseSchemaDataWarehouseTable(
            fields=fields_dict,
            id=str(warehouse_table.id),
            name=table_key,
            format=warehouse_table.format,
            url_pattern=warehouse_table.url_pattern,
            schema=schema,
            source=source,
        )

    # Views
    views = context.database.get_views()
    all_views = list(DataWarehouseSavedQuery.objects.filter(team_id=context.team_id).exclude(deleted=True))
    for view_name in views:
        view: SavedQuery | None = getattr(context.database, view_name, None)
        if view is None:
            continue

        fields = serialize_fields(view.fields, context, view_name, table_type="external")
        fields_dict = {field.name: field for field in fields}

        saved_query: list[DataWarehouseSavedQuery] = list(
            filter(lambda saved_query: saved_query.name == view_name, all_views)
        )
        if len(saved_query) != 0:
            tables[view_name] = DatabaseSchemaViewTable(
                fields=fields_dict, id=str(saved_query[0].pk), name=view.name, query=HogQLQuery(query=view.query)
            )

    return tables


def constant_type_to_serialized_field_type(constant_type: ast.ConstantType) -> DatabaseSerializedFieldType | None:
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
    return None


HOGQL_CHARACTERS_TO_BE_WRAPPED = ["@", "-", "!", "$", "+"]


def serialize_fields(
    field_input,
    context: HogQLContext,
    table_name: str,
    db_columns: Optional[DataWarehouseTableColumns] = None,
    table_type: Literal["posthog"] | Literal["external"] = "posthog",
) -> list[DatabaseSchemaField]:
    from posthog.hogql.database.models import SavedQuery
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

        if field_key == "team_id" and table_type == "posthog":
            pass
        elif isinstance(field, DatabaseField):
            if field.hidden:
                continue

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
            elif isinstance(field, ExpressionField):
                field_expr = resolve_types_from_table(field.expr, table_name, context, "hogql")
                assert field_expr.type is not None
                constant_type = field_expr.type.resolve_constant_type(context)

                field_type = constant_type_to_serialized_field_type(constant_type)
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
