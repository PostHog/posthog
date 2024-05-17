from typing import TYPE_CHECKING, Any, ClassVar, Optional, TypedDict, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import ConfigDict, BaseModel
from sentry_sdk import capture_exception
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    FieldTraverser,
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
from posthog.hogql.database.schema.heatmaps import HeatmapsTable
from posthog.hogql.database.schema.log_entries import (
    LogEntriesTable,
    ReplayConsoleLogsLogEntriesTable,
    BatchExportLogEntriesTable,
)
from posthog.hogql.database.schema.cohort_people import CohortPeople, RawCohortPeople
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.groups import GroupsTable, RawGroupsTable
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
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable, join_with_persons_table
from posthog.hogql.database.schema.person_overrides import (
    PersonOverridesTable,
    RawPersonOverridesTable,
)
from posthog.hogql.database.schema.session_replay_events import (
    RawSessionReplayEventsTable,
    SessionReplayEventsTable,
)
from posthog.hogql.database.schema.sessions import RawSessionsTable, SessionsTable
from posthog.hogql.database.schema.static_cohort_people import StaticCohortPeople
from posthog.hogql.errors import QueryError, ResolutionError
from posthog.hogql.parser import parse_expr
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.team.team import WeekStartDay
from posthog.schema import DatabaseSerializedFieldType, HogQLQueryModifiers, PersonsOnEventsMode
from posthog.warehouse.models.table import DataWarehouseTableColumns

if TYPE_CHECKING:
    from posthog.models import Team


class Database(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Users can query from the tables below
    events: EventsTable = EventsTable()
    groups: GroupsTable = GroupsTable()
    persons: PersonsTable = PersonsTable()
    person_distinct_ids: PersonDistinctIdsTable = PersonDistinctIdsTable()
    person_distinct_id_overrides: PersonDistinctIdOverridesTable = PersonDistinctIdOverridesTable()
    person_overrides: PersonOverridesTable = PersonOverridesTable()

    session_replay_events: SessionReplayEventsTable = SessionReplayEventsTable()
    cohort_people: CohortPeople = CohortPeople()
    static_cohort_people: StaticCohortPeople = StaticCohortPeople()
    log_entries: LogEntriesTable = LogEntriesTable()
    console_logs_log_entries: ReplayConsoleLogsLogEntriesTable = ReplayConsoleLogsLogEntriesTable()
    batch_export_log_entries: BatchExportLogEntriesTable = BatchExportLogEntriesTable()
    sessions: SessionsTable = SessionsTable()
    heatmaps: HeatmapsTable = HeatmapsTable()

    raw_session_replay_events: RawSessionReplayEventsTable = RawSessionReplayEventsTable()
    raw_person_distinct_ids: RawPersonDistinctIdsTable = RawPersonDistinctIdsTable()
    raw_persons: RawPersonsTable = RawPersonsTable()
    raw_groups: RawGroupsTable = RawGroupsTable()
    raw_cohort_people: RawCohortPeople = RawCohortPeople()
    raw_person_distinct_id_overrides: RawPersonDistinctIdOverridesTable = RawPersonDistinctIdOverridesTable()
    raw_person_overrides: RawPersonOverridesTable = RawPersonOverridesTable()
    raw_sessions: RawSessionsTable = RawSessionsTable()

    # system tables
    numbers: NumbersTable = NumbersTable()

    # These are the tables exposed via SQL editor autocomplete and data management
    _table_names: ClassVar[list[str]] = [
        "events",
        "groups",
        "persons",
        "person_distinct_ids",
        "person_overrides",
        "session_replay_events",
        "cohort_people",
        "static_cohort_people",
        "log_entries",
        "sessions",
        "heatmaps",
    ]

    _warehouse_table_names: list[str] = []

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

    def add_warehouse_tables(self, **field_definitions: Any):
        for f_name, f_def in field_definitions.items():
            setattr(self, f_name, f_def)
            self._warehouse_table_names.append(f_name)


def _use_person_properties_from_events(database: Database) -> None:
    database.events.fields["person"] = FieldTraverser(chain=["poe"])


def _use_person_id_from_person_overrides(database: Database) -> None:
    database.events.fields["event_person_id"] = StringDatabaseField(name="person_id")
    database.events.fields["override"] = LazyJoin(
        from_field=["distinct_id"],
        join_table=PersonDistinctIdOverridesTable(),
        join_function=join_with_person_distinct_id_overrides_table,
    )
    database.events.fields["person_id"] = ExpressionField(
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
    from posthog.hogql.query import create_default_modifiers_for_team
    from posthog.warehouse.models import (
        DataWarehouseTable,
        DataWarehouseSavedQuery,
        DataWarehouseJoin,
    )

    team = team_arg or Team.objects.get(pk=team_id)
    modifiers = create_default_modifiers_for_team(team, modifiers)
    database = Database(timezone=team.timezone, week_start_day=team.week_start_day)

    if modifiers.personsOnEventsMode == PersonsOnEventsMode.disabled:
        # no change
        database.events.fields["person"] = FieldTraverser(chain=["pdi", "person"])
        database.events.fields["person_id"] = FieldTraverser(chain=["pdi", "person_id"])

    elif modifiers.personsOnEventsMode == PersonsOnEventsMode.person_id_no_override_properties_on_events:
        database.events.fields["person_id"] = StringDatabaseField(name="person_id")
        _use_person_properties_from_events(database)

    elif modifiers.personsOnEventsMode == PersonsOnEventsMode.person_id_override_properties_on_events:
        _use_person_id_from_person_overrides(database)
        _use_person_properties_from_events(database)
        database.events.fields["poe"].fields["id"] = database.events.fields["person_id"]

    elif modifiers.personsOnEventsMode == PersonsOnEventsMode.person_id_override_properties_joined:
        _use_person_id_from_person_overrides(database)
        database.events.fields["person"] = LazyJoin(
            from_field=["person_id"],
            join_table=PersonsTable(),
            join_function=join_with_persons_table,
        )

    database.persons.fields["$virt_initial_referring_domain_type"] = create_initial_domain_type(
        "$virt_initial_referring_domain_type"
    )
    database.persons.fields["$virt_initial_channel_type"] = create_initial_channel_type("$virt_initial_channel_type")

    for mapping in GroupTypeMapping.objects.filter(team=team):
        if database.events.fields.get(mapping.group_type) is None:
            database.events.fields[mapping.group_type] = FieldTraverser(chain=[f"group_{mapping.group_type_index}"])

    tables: dict[str, Table] = {}
    for table in DataWarehouseTable.objects.filter(team_id=team.pk).exclude(deleted=True):
        tables[table.name] = table.hogql_definition(modifiers)

    if modifiers.dataWarehouseEventsModifiers:
        for warehouse_modifier in modifiers.dataWarehouseEventsModifiers:
            # TODO: add all field mappings
            if "id" not in tables[warehouse_modifier.table_name].fields.keys():
                tables[warehouse_modifier.table_name].fields["id"] = ExpressionField(
                    name="id",
                    expr=parse_expr(warehouse_modifier.id_field),
                )

            if "timestamp" not in tables[warehouse_modifier.table_name].fields.keys():
                table_model = DataWarehouseTable.objects.filter(
                    team_id=team.pk, name=warehouse_modifier.table_name
                ).latest("created_at")
                timestamp_field_type = table_model.get_clickhouse_column_type(warehouse_modifier.timestamp_field)

                # If field type is none or datetime, we can use the field directly
                if timestamp_field_type is None or timestamp_field_type.startswith("DateTime"):
                    tables[warehouse_modifier.table_name].fields["timestamp"] = ExpressionField(
                        name="timestamp",
                        expr=ast.Field(chain=[warehouse_modifier.timestamp_field]),
                    )
                else:
                    tables[warehouse_modifier.table_name].fields["timestamp"] = ExpressionField(
                        name="timestamp",
                        expr=ast.Call(name="toDateTime", args=[ast.Field(chain=[warehouse_modifier.timestamp_field])]),
                    )

            # TODO: Need to decide how the distinct_id and person_id fields are going to be handled
            if "distinct_id" not in tables[warehouse_modifier.table_name].fields.keys():
                tables[warehouse_modifier.table_name].fields["distinct_id"] = ExpressionField(
                    name="distinct_id",
                    expr=parse_expr(warehouse_modifier.distinct_id_field),
                )

            if "person_id" not in tables[warehouse_modifier.table_name].fields.keys():
                tables[warehouse_modifier.table_name].fields["person_id"] = ExpressionField(
                    name="person_id",
                    expr=parse_expr(warehouse_modifier.distinct_id_field),
                )

    for saved_query in DataWarehouseSavedQuery.objects.filter(team_id=team.pk).exclude(deleted=True):
        tables[saved_query.name] = saved_query.hogql_definition()

    database.add_warehouse_tables(**tables)

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
        except Exception as e:
            capture_exception(e)

    return database


class _SerializedFieldBase(TypedDict):
    key: str
    type: DatabaseSerializedFieldType
    schema_valid: bool


class SerializedField(_SerializedFieldBase, total=False):
    fields: list[str]
    table: str
    chain: list[str | int]


def serialize_database(context: HogQLContext) -> dict[str, list[SerializedField]]:
    tables: dict[str, list[SerializedField]] = {}

    if context.database is None:
        raise ResolutionError("Must provide database to serialize_database")

    table_names = context.database.get_posthog_tables()
    for table_key in table_names:
        field_input: dict[str, Any] = {}
        table = getattr(context.database, table_key, None)
        if isinstance(table, FunctionCallTable):
            field_input = table.get_asterisk()
        elif isinstance(table, Table):
            field_input = table.fields

        field_output: list[SerializedField] = serialize_fields(field_input, context)
        tables[table_key] = field_output

    return tables


def serialize_fields(
    field_input, context: HogQLContext, db_columns: Optional[DataWarehouseTableColumns] = None
) -> list[SerializedField]:
    from posthog.hogql.database.models import SavedQuery

    field_output: list[SerializedField] = []
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

        if field_key == "team_id":
            pass
        elif isinstance(field, DatabaseField):
            if field.hidden:
                continue

            if isinstance(field, IntegerDatabaseField):
                field_output.append(
                    {"key": field_key, "type": DatabaseSerializedFieldType.integer, "schema_valid": schema_valid}
                )
            elif isinstance(field, FloatDatabaseField):
                field_output.append(
                    {"key": field_key, "type": DatabaseSerializedFieldType.float, "schema_valid": schema_valid}
                )
            elif isinstance(field, StringDatabaseField):
                field_output.append(
                    {"key": field_key, "type": DatabaseSerializedFieldType.string, "schema_valid": schema_valid}
                )
            elif isinstance(field, DateTimeDatabaseField):
                field_output.append(
                    {"key": field_key, "type": DatabaseSerializedFieldType.datetime, "schema_valid": schema_valid}
                )
            elif isinstance(field, DateDatabaseField):
                field_output.append(
                    {"key": field_key, "type": DatabaseSerializedFieldType.date, "schema_valid": schema_valid}
                )
            elif isinstance(field, BooleanDatabaseField):
                field_output.append(
                    {"key": field_key, "type": DatabaseSerializedFieldType.boolean, "schema_valid": schema_valid}
                )
            elif isinstance(field, StringJSONDatabaseField):
                field_output.append(
                    {"key": field_key, "type": DatabaseSerializedFieldType.json, "schema_valid": schema_valid}
                )
            elif isinstance(field, StringArrayDatabaseField):
                field_output.append(
                    {"key": field_key, "type": DatabaseSerializedFieldType.array, "schema_valid": schema_valid}
                )
            elif isinstance(field, ExpressionField):
                field_output.append(
                    {"key": field_key, "type": DatabaseSerializedFieldType.expression, "schema_valid": schema_valid}
                )
        elif isinstance(field, LazyJoin):
            is_view = isinstance(field.resolve_table(context), SavedQuery)
            field_output.append(
                {
                    "key": field_key,
                    "type": DatabaseSerializedFieldType.view if is_view else DatabaseSerializedFieldType.lazy_table,
                    "table": field.resolve_table(context).to_printed_hogql(),
                    "fields": list(field.resolve_table(context).fields.keys()),
                    "schema_valid": schema_valid,
                }
            )
        elif isinstance(field, VirtualTable):
            field_output.append(
                {
                    "key": field_key,
                    "type": DatabaseSerializedFieldType.virtual_table,
                    "table": field.to_printed_hogql(),
                    "fields": list(field.fields.keys()),
                    "schema_valid": schema_valid,
                }
            )
        elif isinstance(field, FieldTraverser):
            field_output.append(
                {
                    "key": field_key,
                    "type": DatabaseSerializedFieldType.field_traverser,
                    "chain": field.chain,
                    "schema_valid": schema_valid,
                }
            )
    return field_output
