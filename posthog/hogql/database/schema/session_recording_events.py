from typing import Dict

from posthog.hogql.database.models import (
    Table,
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    StringJSONDatabaseField,
    BooleanDatabaseField,
    LazyJoin,
    FieldTraverser,
    FieldOrTable,
)
from posthog.hogql.database.schema.person_distinct_ids import (
    PersonDistinctIdsTable,
    join_with_person_distinct_ids_table,
)


class SessionRecordingEvents(Table):
    fields: Dict[str, FieldOrTable] = {
        "uuid": StringDatabaseField(name="uuid"),
        "timestamp": DateTimeDatabaseField(name="timestamp"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "distinct_id": StringDatabaseField(name="distinct_id"),
        "session_id": StringDatabaseField(name="session_id"),
        "window_id": StringDatabaseField(name="window_id"),
        "snapshot_data": StringJSONDatabaseField(name="snapshot_data"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "has_full_snapshot": BooleanDatabaseField(name="has_full_snapshot"),
        "events_summary": StringJSONDatabaseField(name="events_summary", array=True),
        "click_count": IntegerDatabaseField(name="click_count"),
        "keypress_count": IntegerDatabaseField(name="keypress_count"),
        "timestamps_summary": DateTimeDatabaseField(name="timestamps_summary", array=True),
        "first_event_timestamp": DateTimeDatabaseField(name="first_event_timestamp"),
        "last_event_timestamp": DateTimeDatabaseField(name="last_event_timestamp"),
        "urls": StringDatabaseField(name="urls", array=True),
        "pdi": LazyJoin(
            from_field="distinct_id",
            join_table=PersonDistinctIdsTable(),
            join_function=join_with_person_distinct_ids_table,
        ),
        "person": FieldTraverser(chain=["pdi", "person"]),
        "person_id": FieldTraverser(chain=["pdi", "person_id"]),
    }

    def to_printed_clickhouse(self, context):
        return "session_recording_events"

    def to_printed_hogql(self):
        return "session_recording_events"
