from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, Extra

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
from posthog.hogql.database.schema.person_distinct_ids import PersonDistinctIdsTable, RawPersonDistinctIdsTable
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable
from posthog.hogql.database.schema.person_overrides import PersonOverridesTable, RawPersonOverridesTable
from posthog.hogql.database.schema.session_recording_events import SessionRecordingEvents
from posthog.hogql.database.schema.session_replay_events import RawSessionReplayEventsTable, SessionReplayEventsTable
from posthog.hogql.database.schema.static_cohort_people import StaticCohortPeople
from posthog.hogql.errors import HogQLException
from posthog.utils import PersonOnEventsMode


class Database(BaseModel):
    class Config:
        extra = Extra.allow

    # Users can query from the tables below
    events: EventsTable = EventsTable()
    groups: GroupsTable = GroupsTable()
    persons: PersonsTable = PersonsTable()
    person_distinct_ids: PersonDistinctIdsTable = PersonDistinctIdsTable()
    person_overrides: PersonOverridesTable = PersonOverridesTable()

    session_recording_events: SessionRecordingEvents = SessionRecordingEvents()
    session_replay_events: SessionReplayEventsTable = SessionReplayEventsTable()
    cohort_people: CohortPeople = CohortPeople()
    static_cohort_people: StaticCohortPeople = StaticCohortPeople()

    raw_session_replay_events: RawSessionReplayEventsTable = RawSessionReplayEventsTable()
    raw_person_distinct_ids: RawPersonDistinctIdsTable = RawPersonDistinctIdsTable()
    raw_persons: RawPersonsTable = RawPersonsTable()
    raw_groups: RawGroupsTable = RawGroupsTable()
    raw_cohort_people: RawCohortPeople = RawCohortPeople()
    raw_person_overrides: RawPersonOverridesTable = RawPersonOverridesTable()

    def __init__(self, timezone: Optional[str]):
        super().__init__()
        try:
            self._timezone = str(ZoneInfo(timezone)) if timezone else None
        except ZoneInfoNotFoundError:
            raise HogQLException(f"Unknown timezone: '{str(timezone)}'")

    def get_timezone(self) -> str:
        return self._timezone or "UTC"

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
    from posthog.warehouse.models import DataWarehouseTable

    team = Team.objects.get(pk=team_id)
    database = Database(timezone=team.timezone)
    if team.person_on_events_mode != PersonOnEventsMode.DISABLED:
        # TODO: split PoE v1 and v2 once SQL Expression fields are supported #15180
        database.events.fields["person"] = FieldTraverser(chain=["poe"])
        database.events.fields["person_id"] = StringDatabaseField(name="person_id")

    tables = {}
    for table in DataWarehouseTable.objects.filter(team_id=team.pk).exclude(deleted=True):
        tables[table.name] = table.hogql_definition()
    database.add_warehouse_tables(**tables)

    return database


def serialize_database(database: Database) -> dict:
    tables: Dict[str, List[Dict[str, Any]]] = {}

    for table_key in database.__fields__.keys():
        field_input: Dict[str, Any] = {}
        table = getattr(database, table_key, None)
        if isinstance(table, FunctionCallTable):
            field_input = table.get_asterisk()
        elif isinstance(table, Table):
            field_input = table.fields

        field_output: List[Dict[str, Any]] = serialize_fields(field_input)
        tables[table_key] = field_output

    return tables


def serialize_fields(field_input) -> List[Dict[str, Any]]:
    field_output: List[Dict[str, Any]] = []
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
            field_output.append({"key": field_key, "type": "lazy_table", "table": field.join_table.to_printed_hogql()})
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
