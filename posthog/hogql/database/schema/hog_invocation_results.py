from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

# One row per CDP invocation lifecycle event (start + finish, plus a row per replay).
# The underlying ClickHouse table is a sharded ReplacingMergeTree keyed by
# (team_id, function_kind, function_id, invocation_id) with `version` as the
# tie-breaker — when querying, group by invocation_id and use argMax(field, version)
# to get the latest state, the same way persons are read.
HOG_INVOCATION_RESULTS_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "function_kind": StringDatabaseField(name="function_kind", nullable=False),
    "function_id": StringDatabaseField(name="function_id", nullable=False),
    "invocation_id": StringDatabaseField(name="invocation_id", nullable=False),
    "parent_run_id": StringDatabaseField(name="parent_run_id", nullable=False),
    "status": StringDatabaseField(name="status", nullable=False),
    "attempts": IntegerDatabaseField(name="attempts", nullable=False),
    "is_retry": BooleanDatabaseField(name="is_retry", nullable=False),
    "scheduled_at": DateTimeDatabaseField(name="scheduled_at", nullable=False),
    "started_at": DateTimeDatabaseField(name="started_at", nullable=True),
    "finished_at": DateTimeDatabaseField(name="finished_at", nullable=True),
    "duration_ms": IntegerDatabaseField(name="duration_ms", nullable=True),
    "error_kind": StringDatabaseField(name="error_kind", nullable=False),
    "error_message": StringDatabaseField(name="error_message", nullable=False),
    "event_uuid": StringDatabaseField(name="event_uuid", nullable=False),
    "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
    "person_id": StringDatabaseField(name="person_id", nullable=False),
    "invocation_globals": StringDatabaseField(name="invocation_globals", nullable=False),
    "version": IntegerDatabaseField(name="version", nullable=False),
    "is_deleted": BooleanDatabaseField(name="is_deleted", nullable=False),
}


class HogInvocationResultsTable(Table):
    fields: dict[str, FieldOrTable] = HOG_INVOCATION_RESULTS_FIELDS

    def to_printed_clickhouse(self, context):
        return "hog_invocation_results"

    def to_printed_hogql(self):
        return "hog_invocation_results"
