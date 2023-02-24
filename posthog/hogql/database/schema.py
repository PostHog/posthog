from pydantic import BaseModel, Extra

from posthog.hogql.database.joins import join_with_max_person_distinct_id_table, join_with_persons_table
from posthog.hogql.database.primitives import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldTraverser,
    IntegerDatabaseField,
    LazyTable,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    VirtualTable,
)


class EventsPersonSubTable(VirtualTable):
    id: StringDatabaseField = StringDatabaseField(name="person_id")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="person_created_at")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="person_properties")

    def clickhouse_table(self):
        return "events"


class PersonsTable(Table):
    id: StringDatabaseField = StringDatabaseField(name="id")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="properties")
    is_identified: BooleanDatabaseField = BooleanDatabaseField(name="is_identified")
    is_deleted: BooleanDatabaseField = BooleanDatabaseField(name="is_deleted")
    version: IntegerDatabaseField = IntegerDatabaseField(name="version")

    def clickhouse_table(self):
        return "person"


class PersonStaticCohortTable(Table):
    id: StringDatabaseField = StringDatabaseField(name="id")
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    cohort_id: IntegerDatabaseField = IntegerDatabaseField(name="cohort_id")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")

    person: LazyTable = LazyTable(from_field="person_id", table=PersonsTable(), join_function=join_with_persons_table)

    def clickhouse_table(self):
        return "person_static_cohort"


class CohortPeopleTable(Table):
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    cohort_id: IntegerDatabaseField = IntegerDatabaseField(name="cohort_id")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    sign: IntegerDatabaseField = IntegerDatabaseField(name="sign")
    version: IntegerDatabaseField = IntegerDatabaseField(name="version")

    person: LazyTable = LazyTable(from_field="person_id", table=PersonsTable(), join_function=join_with_persons_table)

    def clickhouse_table(self):
        return "cohortpeople"


class PersonDistinctIdTable(Table):
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    distinct_id: StringDatabaseField = StringDatabaseField(name="distinct_id")
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    is_deleted: BooleanDatabaseField = BooleanDatabaseField(name="is_deleted")
    version: IntegerDatabaseField = IntegerDatabaseField(name="version")

    person: LazyTable = LazyTable(from_field="person_id", table=PersonsTable(), join_function=join_with_persons_table)

    # static_cohorts: LazyTable(from_field="person_id", table=)

    def avoid_asterisk_fields(self):
        return ["is_deleted", "version"]

    def clickhouse_table(self):
        return "person_distinct_id2"


class EventsTable(Table):
    uuid: StringDatabaseField = StringDatabaseField(name="uuid")
    event: StringDatabaseField = StringDatabaseField(name="event")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="properties")
    timestamp: DateTimeDatabaseField = DateTimeDatabaseField(name="timestamp")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    distinct_id: StringDatabaseField = StringDatabaseField(name="distinct_id")
    elements_chain: StringDatabaseField = StringDatabaseField(name="elements_chain")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")

    # lazy table that adds a join to the persons table
    pdi: LazyTable = LazyTable(
        from_field="distinct_id", table=PersonDistinctIdTable(), join_function=join_with_max_person_distinct_id_table
    )
    # person fields on the event itself
    poe: EventsPersonSubTable = EventsPersonSubTable()

    # TODO: swap these between pdi and person_on_events as needed
    person: FieldTraverser = FieldTraverser(chain=["pdi", "person"])
    person_id: FieldTraverser = FieldTraverser(chain=["pdi", "person_id"])

    def clickhouse_table(self):
        return "events"


class SessionRecordingEvents(Table):
    uuid: StringDatabaseField = StringDatabaseField(name="uuid")
    timestamp: DateTimeDatabaseField = DateTimeDatabaseField(name="timestamp")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    distinct_id: StringDatabaseField = StringDatabaseField(name="distinct_id")
    session_id: StringDatabaseField = StringDatabaseField(name="session_id")
    window_id: StringDatabaseField = StringDatabaseField(name="window_id")
    snapshot_data: StringJSONDatabaseField = StringJSONDatabaseField(name="snapshot_data")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")
    has_full_snapshot: BooleanDatabaseField = BooleanDatabaseField(name="has_full_snapshot")
    events_summary: StringJSONDatabaseField = StringJSONDatabaseField(name="events_summary", array=True)
    click_count: IntegerDatabaseField = IntegerDatabaseField(name="click_count")
    keypress_count: IntegerDatabaseField = IntegerDatabaseField(name="keypress_count")
    timestamps_summary: DateTimeDatabaseField = DateTimeDatabaseField(name="timestamps_summary", array=True)
    first_event_timestamp: DateTimeDatabaseField = DateTimeDatabaseField(name="first_event_timestamp")
    last_event_timestamp: DateTimeDatabaseField = DateTimeDatabaseField(name="last_event_timestamp")
    urls: StringDatabaseField = StringDatabaseField(name="urls", array=True)

    pdi: LazyTable = LazyTable(
        from_field="distinct_id", table=PersonDistinctIdTable(), join_function=join_with_max_person_distinct_id_table
    )

    def clickhouse_table(self):
        return "session_recording_events"


class Database(BaseModel):
    class Config:
        extra = Extra.forbid

    # Users can query from the tables below
    events: EventsTable = EventsTable()
    persons: PersonsTable = PersonsTable()
    person_distinct_ids: PersonDistinctIdTable = PersonDistinctIdTable()
    session_recording_events: SessionRecordingEvents = SessionRecordingEvents()

    def has_table(self, table_name: str) -> bool:
        return hasattr(self, table_name)

    def get_table(self, table_name: str) -> Table:
        if self.has_table(table_name):
            return getattr(self, table_name)
        raise ValueError(f'Table "{table_name}" not found in database')


database = Database()
