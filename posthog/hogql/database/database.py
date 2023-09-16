from typing import Any, ClassVar, Dict, List, Literal, Optional, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import ConfigDict, BaseModel

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
)
from posthog.hogql.database.schema.cohort_people import CohortPeople, RawCohortPeople
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.groups import GroupsTable, RawGroupsTable
from posthog.hogql.database.schema.numbers import NumbersTable
from posthog.hogql.database.schema.person_distinct_ids import PersonDistinctIdsTable, RawPersonDistinctIdsTable
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable
from posthog.hogql.database.schema.person_overrides import PersonOverridesTable, RawPersonOverridesTable
from posthog.hogql.database.schema.session_replay_events import RawSessionReplayEventsTable, SessionReplayEventsTable
from posthog.hogql.database.schema.static_cohort_people import StaticCohortPeople
from posthog.hogql.errors import HogQLException
from posthog.models.team.team import WeekStartDay
from posthog.utils import PersonOnEventsMode


class Database(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Users can query from the tables below
    events: EventsTable = EventsTable()
    groups: GroupsTable = GroupsTable()
    persons: PersonsTable = PersonsTable()
    person_distinct_ids: PersonDistinctIdsTable = PersonDistinctIdsTable()
    person_overrides: PersonOverridesTable = PersonOverridesTable()

    session_replay_events: SessionReplayEventsTable = SessionReplayEventsTable()
    cohort_people: CohortPeople = CohortPeople()
    static_cohort_people: StaticCohortPeople = StaticCohortPeople()

    raw_session_replay_events: RawSessionReplayEventsTable = RawSessionReplayEventsTable()
    raw_person_distinct_ids: RawPersonDistinctIdsTable = RawPersonDistinctIdsTable()
    raw_persons: RawPersonsTable = RawPersonsTable()
    raw_groups: RawGroupsTable = RawGroupsTable()
    raw_cohort_people: RawCohortPeople = RawCohortPeople()
    raw_person_overrides: RawPersonOverridesTable = RawPersonOverridesTable()

    # system tables
    numbers: NumbersTable = NumbersTable()

    # clunky: keep table names in sync with above
    _table_names: ClassVar[List[str]] = [
        "events",
        "groups",
        "person",
        "person_distinct_id2",
        "person_overrides",
        "session_recording_events",
        "session_replay_events",
        "cohortpeople",
        "person_static_cohort",
    ]

    _timezone: Optional[str]
    _week_start_day: Optional[WeekStartDay]

    def __init__(self, timezone: Optional[str], week_start_day: Optional[WeekStartDay]):
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

    def add_warehouse_tables(self, **field_definitions: Any):
        for f_name, f_def in field_definitions.items():
            setattr(self, f_name, f_def)


def create_hogql_database(team_id: int) -> Database:
    from posthog.models import Team
    from posthog.warehouse.models import DataWarehouseTable, DataWarehouseSavedQuery, DataWarehouseViewLink

    team = Team.objects.get(pk=team_id)
    database = Database(timezone=team.timezone, week_start_day=team.week_start_day)
    if team.person_on_events_mode != PersonOnEventsMode.DISABLED:
        # TODO: split PoE v1 and v2 once SQL Expression fields are supported #15180
        database.events.fields["person"] = FieldTraverser(chain=["poe"])
        database.events.fields["person_id"] = StringDatabaseField(name="person_id")

    for view in DataWarehouseViewLink.objects.filter(team_id=team.pk).exclude(deleted=True):
        table = database.get_table(view.table)

        # Saved query names are unique to team
        table.fields[view.saved_query.name] = LazyJoin(
            from_field=view.from_join_key,
            join_table=view.saved_query.hogql_definition(),
            join_function=view.join_function,
        )

    tables = {}
    for table in DataWarehouseTable.objects.filter(team_id=team.pk).exclude(deleted=True):
        tables[table.name] = table.hogql_definition()

    for table in DataWarehouseSavedQuery.objects.filter(team_id=team.pk).exclude(deleted=True):
        tables[table.name] = table.hogql_definition()

    database.add_warehouse_tables(**tables)

    return database


def determine_join_function(view):
    def join_function(from_table: str, to_table: str, requested_fields: Dict[str, Any]):
        from posthog.hogql import ast
        from posthog.hogql.parser import parse_select

        if not requested_fields:
            raise HogQLException(f"No fields requested from {to_table}")

        join_expr = ast.JoinExpr(table=parse_select(view.saved_query.query["query"]))
        join_expr.join_type = "INNER JOIN"
        join_expr.alias = to_table
        join_expr.constraint = ast.JoinConstraint(
            expr=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[from_table, view.from_join_key]),
                right=ast.Field(chain=[to_table, view.to_join_key]),
            )
        )
        return join_expr

    return join_function


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
    ]


class SerializedField(_SerializedFieldBase, total=False):
    fields: List[str]
    table: str
    chain: List[str]


def serialize_database(database: Database) -> Dict[str, List[SerializedField]]:
    tables: Dict[str, List[SerializedField]] = {}

    for table_key in database.model_fields.keys():
        field_input: Dict[str, Any] = {}
        table = getattr(database, table_key, None)
        if isinstance(table, FunctionCallTable):
            field_input = table.get_asterisk()
        elif isinstance(table, Table):
            field_input = table.fields

        field_output: List[SerializedField] = serialize_fields(field_input)
        tables[table_key] = field_output

    return tables


def serialize_fields(field_input) -> List[SerializedField]:
    from posthog.hogql.database.models import SavedQuery

    field_output: List[SerializedField] = []
    for field_key, field in field_input.items():
        if field_key == "team_id":
            pass
        elif isinstance(field, DatabaseField):
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
        elif isinstance(field, LazyJoin):
            is_view = isinstance(field.join_table, SavedQuery)
            field_output.append(
                {
                    "key": field_key,
                    "type": "view" if is_view else "lazy_table",
                    "table": field.join_table.to_printed_hogql(),
                    "fields": list(field.join_table.fields.keys()),
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
