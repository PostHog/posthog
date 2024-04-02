from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Literal, Optional, TypedDict
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
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable
from posthog.hogql.database.schema.person_overrides import (
    PersonOverridesTable,
    RawPersonOverridesTable,
    join_with_person_overrides_table,
)
from posthog.hogql.database.schema.session_replay_events import (
    RawSessionReplayEventsTable,
    SessionReplayEventsTable,
)
from posthog.hogql.database.schema.sessions import RawSessionsTable, SessionsTable
from posthog.hogql.database.schema.static_cohort_people import StaticCohortPeople
from posthog.hogql.errors import HogQLException
from posthog.hogql.parser import parse_expr
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.team.team import WeekStartDay
from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

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

    # clunky: keep table names in sync with above
    _table_names: ClassVar[List[str]] = [
        "events",
        "groups",
        "persons",
        "person_distinct_id2",
        "person_overrides",
        "session_replay_events",
        "cohortpeople",
        "person_static_cohort",
        "log_entries",
        "sessions",
    ]

    _warehouse_table_names: List[str] = []

    _timezone: Optional[str]
    _week_start_day: Optional[WeekStartDay]

    def __init__(self, timezone: Optional[str] = None, week_start_day: Optional[WeekStartDay] = None):
        super().__init__()
        try:
            self._timezone = str(ZoneInfo(timezone)) if timezone else None
        except ZoneInfoNotFoundError:
            raise HogQLException(f"Unknown timezone: '{str(timezone)}'")
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
        raise HogQLException(f'Table "{table_name}" not found in database')

    def get_all_tables(self) -> List[str]:
        return self._table_names + self._warehouse_table_names

    def add_warehouse_tables(self, **field_definitions: Any):
        for f_name, f_def in field_definitions.items():
            setattr(self, f_name, f_def)
            self._warehouse_table_names.append(f_name)


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

    elif modifiers.personsOnEventsMode == PersonsOnEventsMode.v1_mixed:
        # person.id via a join, person.properties on events
        database.events.fields["person_id"] = FieldTraverser(chain=["pdi", "person_id"])
        database.events.fields["person"] = FieldTraverser(chain=["poe"])
        database.events.fields["poe"].fields["id"] = FieldTraverser(chain=["..", "pdi", "person_id"])
        database.events.fields["poe"].fields["created_at"] = FieldTraverser(chain=["..", "pdi", "person", "created_at"])
        database.events.fields["poe"].fields["properties"] = StringJSONDatabaseField(name="person_properties")

    elif modifiers.personsOnEventsMode == PersonsOnEventsMode.v1_enabled:
        database.events.fields["person"] = FieldTraverser(chain=["poe"])
        database.events.fields["person_id"] = StringDatabaseField(name="person_id")

    elif modifiers.personsOnEventsMode == PersonsOnEventsMode.v2_enabled:
        database.events.fields["event_person_id"] = StringDatabaseField(name="person_id")
        database.events.fields["override"] = LazyJoin(
            from_field=["event_person_id"],
            join_table=PersonOverridesTable(),
            join_function=join_with_person_overrides_table,
        )
        database.events.fields["person_id"] = ExpressionField(
            name="person_id",
            expr=parse_expr(
                "ifNull(nullIf(override.override_person_id, '00000000-0000-0000-0000-000000000000'), event_person_id)",
                start=None,
            ),
        )
        database.events.fields["poe"].fields["id"] = database.events.fields["person_id"]
        database.events.fields["person"] = FieldTraverser(chain=["poe"])

    elif modifiers.personsOnEventsMode == PersonsOnEventsMode.v3_enabled:
        database.events.fields["event_person_id"] = StringDatabaseField(name="person_id")
        database.events.fields["override"] = LazyJoin(
            from_field=["distinct_id"],  # ???
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
        database.events.fields["poe"].fields["id"] = database.events.fields["person_id"]
        database.events.fields["person"] = FieldTraverser(chain=["poe"])

    database.persons.fields["$virt_initial_referring_domain_type"] = create_initial_domain_type(
        "$virt_initial_referring_domain_type"
    )
    database.persons.fields["$virt_initial_channel_type"] = create_initial_channel_type("$virt_initial_channel_type")

    for mapping in GroupTypeMapping.objects.filter(team=team):
        if database.events.fields.get(mapping.group_type) is None:
            database.events.fields[mapping.group_type] = FieldTraverser(chain=[f"group_{mapping.group_type_index}"])

    tables: Dict[str, Table] = {}
    for table in DataWarehouseTable.objects.filter(team_id=team.pk).exclude(deleted=True):
        tables[table.name] = table.hogql_definition()

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
        try:
            source_table = database.get_table(join.source_table_name)
            joining_table = database.get_table(join.joining_table_name)

            field = parse_expr(join.source_table_key)
            if not isinstance(field, ast.Field):
                raise HogQLException("Data Warehouse Join HogQL expression should be a Field node")
            from_field = field.chain

            field = parse_expr(join.joining_table_key)
            if not isinstance(field, ast.Field):
                raise HogQLException("Data Warehouse Join HogQL expression should be a Field node")
            to_field = field.chain

            source_table.fields[join.field_name] = LazyJoin(
                from_field=from_field,
                to_field=to_field,
                join_table=joining_table,
                join_function=join.join_function,
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
                            join_function=join.join_function,
                        )
                    else:
                        table_or_field.fields[join.field_name] = LazyJoin(
                            from_field=from_field,
                            to_field=to_field,
                            join_table=joining_table,
                            join_function=join.join_function,
                        )
        except Exception as e:
            capture_exception(e)

    return database


class _SerializedFieldBase(TypedDict):
    key: str
    type: Literal[
        "integer",
        "float",
        "string",
        "datetime",
        "date",
        "boolean",
        "array",
        "json",
        "lazy_table",
        "virtual_table",
        "field_traverser",
        "expression",
    ]


class SerializedField(_SerializedFieldBase, total=False):
    fields: List[str]
    table: str
    chain: List[str]


def serialize_database(context: HogQLContext) -> Dict[str, List[SerializedField]]:
    tables: Dict[str, List[SerializedField]] = {}

    if context.database is None:
        raise HogQLException("Must provide database to serialize_database")

    for table_key in context.database.model_fields.keys():
        field_input: Dict[str, Any] = {}
        table = getattr(context.database, table_key, None)
        if isinstance(table, FunctionCallTable):
            field_input = table.get_asterisk()
        elif isinstance(table, Table):
            field_input = table.fields

        field_output: List[SerializedField] = serialize_fields(field_input, context)
        tables[table_key] = field_output

    return tables


def serialize_fields(field_input, context: HogQLContext) -> List[SerializedField]:
    from posthog.hogql.database.models import SavedQuery

    field_output: List[SerializedField] = []
    for field_key, field in field_input.items():
        if field_key == "team_id":
            pass
        elif isinstance(field, DatabaseField):
            if field.hidden:
                continue

            if isinstance(field, IntegerDatabaseField):
                field_output.append({"key": field_key, "type": "integer"})
            elif isinstance(field, FloatDatabaseField):
                field_output.append({"key": field_key, "type": "float"})
            elif isinstance(field, StringDatabaseField):
                field_output.append({"key": field_key, "type": "string"})
            elif isinstance(field, DateTimeDatabaseField):
                field_output.append({"key": field_key, "type": "datetime"})
            elif isinstance(field, DateDatabaseField):
                field_output.append({"key": field_key, "type": "date"})
            elif isinstance(field, BooleanDatabaseField):
                field_output.append({"key": field_key, "type": "boolean"})
            elif isinstance(field, StringJSONDatabaseField):
                field_output.append({"key": field_key, "type": "json"})
            elif isinstance(field, StringArrayDatabaseField):
                field_output.append({"key": field_key, "type": "array"})
            elif isinstance(field, ExpressionField):
                field_output.append({"key": field_key, "type": "expression"})
        elif isinstance(field, LazyJoin):
            is_view = isinstance(field.resolve_table(context), SavedQuery)
            field_output.append(
                {
                    "key": field_key,
                    "type": "view" if is_view else "lazy_table",
                    "table": field.resolve_table(context).to_printed_hogql(),
                    "fields": list(field.resolve_table(context).fields.keys()),
                }
            )
        elif isinstance(field, VirtualTable):
            field_output.append(
                {
                    "key": field_key,
                    "type": "virtual_table",
                    "table": field.to_printed_hogql(),
                    "fields": list(field.fields.keys()),
                }
            )
        elif isinstance(field, FieldTraverser):
            field_output.append({"key": field_key, "type": "field_traverser", "chain": field.chain})
    return field_output
