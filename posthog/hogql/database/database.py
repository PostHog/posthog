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
    LazyJoin,
    VirtualTable,
    Table,
)
from posthog.hogql.database.schema.cohort_people import CohortPeople, RawCohortPeople
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.groups import GroupsTable, RawGroupsTable
from posthog.hogql.database.schema.person_distinct_ids import PersonDistinctIdTable, RawPersonDistinctIdTable
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable
from posthog.hogql.database.schema.person_overrides import PersonOverridesTable, RawPersonOverridesTable
from posthog.hogql.database.schema.session_recording_events import SessionRecordingEvents
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
    person_distinct_ids: PersonDistinctIdTable = PersonDistinctIdTable()
    person_overrides: PersonOverridesTable = PersonOverridesTable()

    session_recording_events: SessionRecordingEvents = SessionRecordingEvents()
    cohort_people: CohortPeople = CohortPeople()
    static_cohort_people: StaticCohortPeople = StaticCohortPeople()

    raw_person_distinct_ids: RawPersonDistinctIdTable = RawPersonDistinctIdTable()
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


def create_hogql_database(team_id: int) -> Database:
    from posthog.models import Team

    team = Team.objects.get(pk=team_id)
    database = Database(timezone=team.timezone)
    if team.person_on_events_mode != PersonOnEventsMode.DISABLED:
        # TODO: split PoE v1 and v2 once SQL Expression fields are supported #15180
        database.events.person = FieldTraverser(chain=["poe"])
        database.events.person_id = StringDatabaseField(name="person_id")
    return database


def serialize_database(database: Database) -> dict:
    tables: Dict[str, List[Dict[str, Any]]] = {}

    for table_key in database.__fields__.keys():
        fields: List[Dict[str, Any]] = []
        table = getattr(database, table_key, None)
        for field_key in table.__fields__.keys() if table else []:
            field = getattr(table, field_key, None)
            if field_key == "team_id":
                pass
            elif isinstance(field, DatabaseField):
                if isinstance(field, IntegerDatabaseField):
                    fields.append({"key": field_key, "type": "integer"})
                elif isinstance(field, StringDatabaseField):
                    fields.append({"key": field_key, "type": "string"})
                elif isinstance(field, DateTimeDatabaseField):
                    fields.append({"key": field_key, "type": "datetime"})
                elif isinstance(field, BooleanDatabaseField):
                    fields.append({"key": field_key, "type": "boolean"})
                elif isinstance(field, StringJSONDatabaseField):
                    fields.append({"key": field_key, "type": "json"})
            elif isinstance(field, LazyJoin):
                fields.append({"key": field_key, "type": "lazy_table", "table": field.join_table.hogql_table()})
            elif isinstance(field, VirtualTable):
                fields.append(
                    {
                        "key": field_key,
                        "type": "virtual_table",
                        "table": field.hogql_table(),
                        "fields": list(field.__fields__.keys()),
                    }
                )
            elif isinstance(field, FieldTraverser):
                fields.append({"key": field_key, "type": "field_traverser", "chain": field.chain})
        tables[table_key] = fields

    return tables
