from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

# One row per CDP invocation lifecycle event (start + finish, plus a row per rerun).
# The underlying ClickHouse table is a sharded ReplacingMergeTree keyed by
# (team_id, function_kind, function_id, invocation_id) with `version` as the
# tie-breaker — when querying, group by invocation_id and use argMax(field, version)
# to get the latest state, the same way persons are read.
#
# Access scope: this table is registered with HogQL under the standard team_id
# guard — same scope as `app_metrics2`, `metrics`, and other operational tables.
# Per-function / per-workflow access controls are NOT enforced here; any user
# with project query access can SELECT lifecycle rows (invocation_id, status,
# error_kind/message, event/person identifiers) for every function and flow
# in the project. Sensitive payload fields are excluded (see next paragraph),
# and the runs UI gates on function/flow access at the parent scene level.
#
# `invocation_globals` is intentionally NOT exposed here. The column carries the
# full rerun payload — for hog functions whose trigger is a source webhook, that
# includes `request.headers` (authorization, x-api-key, etc.). We don't want a
# tenant to be able to SELECT those via /api/projects/:id/query. The rerun path
# reads `invocation_globals` via the internal ClickHouse client (not HogQL) and
# strips `request.headers` for webhook sources at rehydration, so leaving the
# column off the HogQL schema entirely costs nothing for rerun. If the runs UI
# ever wants a "view payload" affordance, that should land as a server-side
# endpoint that gates on the function's write permission, not as a HogQL query.
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
    "first_scheduled_at": DateTimeDatabaseField(name="first_scheduled_at", nullable=False),
    "started_at": DateTimeDatabaseField(name="started_at", nullable=True),
    "finished_at": DateTimeDatabaseField(name="finished_at", nullable=True),
    "duration_ms": IntegerDatabaseField(name="duration_ms", nullable=True),
    "error_kind": StringDatabaseField(name="error_kind", nullable=False),
    "error_message": StringDatabaseField(name="error_message", nullable=False),
    "event_uuid": StringDatabaseField(name="event_uuid", nullable=False),
    "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
    "person_id": StringDatabaseField(name="person_id", nullable=False),
    "version": IntegerDatabaseField(name="version", nullable=False),
    "is_deleted": BooleanDatabaseField(name="is_deleted", nullable=False),
}


class HogInvocationResultsTable(Table):
    fields: dict[str, FieldOrTable] = HOG_INVOCATION_RESULTS_FIELDS

    def to_printed_clickhouse(self, context):
        return "hog_invocation_results"

    def to_printed_hogql(self):
        return "hog_invocation_results"
