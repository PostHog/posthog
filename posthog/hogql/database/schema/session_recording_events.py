from posthog.hogql.database.models import (
    Table,
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    StringJSONDatabaseField,
    BooleanDatabaseField,
    LazyJoin,
    FieldTraverser,
)
from posthog.hogql.database.schema.person_distinct_ids import PersonDistinctIdTable, join_with_person_distinct_ids_table


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

    pdi: LazyJoin = LazyJoin(
        from_field="distinct_id",
        join_table=PersonDistinctIdTable(),
        join_function=join_with_person_distinct_ids_table,
    )

    person: FieldTraverser = FieldTraverser(chain=["pdi", "person"])
    person_id: FieldTraverser = FieldTraverser(chain=["pdi", "person_id"])

    def clickhouse_table(self):
        return "session_recording_events"

    def hogql_table(self):
        return "session_recording_events"
