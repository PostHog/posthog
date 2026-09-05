from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    FieldTraverser,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    UUIDDatabaseField,
    VirtualTable,
)

# The physical read table is the Distributed `flag_evaluations` on the DATA nodes, defined in
# posthog/models/flag_evaluations/sql.py. That module imports django.conf, and
# posthog/hogql/test/test_no_django_imports.py imports this package with no django.setup(), so the
# name is spelled out here rather than imported.
FLAG_EVALUATIONS_CLICKHOUSE_TABLE = "flag_evaluations"


class FlagEvaluationsPersonSubTable(VirtualTable):
    """Person columns carried on the flag-evaluation row itself.

    Narrower than EventsPersonSubTable, which also declares `person_created_at` -- a column this
    table does not store, so reusing it would let `person.created_at` and `SELECT person.*`
    compile into a column the shards lack.
    """

    fields: dict[str, FieldOrTable] = {
        "id": UUIDDatabaseField(name="person_id", nullable=False),
        "properties": StringJSONDatabaseField(name="person_properties", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return FLAG_EVALUATIONS_CLICKHOUSE_TABLE

    def to_printed_hogql(self):
        return FLAG_EVALUATIONS_CLICKHOUSE_TABLE


class FlagEvaluationsTable(Table):
    description: str = (
        "One row per feature flag evaluation, from the `$feature_flag_called` event. Rows are kept for 90 days. "
        "A project that is not sending flag-evaluation telemetry yet sees an empty table."
    )
    fields: dict[str, FieldOrTable] = {
        "uuid": UUIDDatabaseField(name="uuid", nullable=False, description="Unique identifier of this row."),
        "event": StringDatabaseField(
            name="event",
            nullable=False,
            description="Always '$feature_flag_called'.",
        ),
        "properties": StringJSONDatabaseField(
            name="properties",
            nullable=False,
            description="JSON map of the event's properties. Access nested keys with `properties.$lib` etc. "
            "Prefer the `flag_key`, `response`, `session_id`, `request_id` and `$group_0`..`$group_4` columns "
            "where they cover what you need: reading the same value out of this JSON scans far more data.",
        ),
        "timestamp": DateTimeDatabaseField(
            name="timestamp", nullable=False, description="When the flag was evaluated (client timestamp, in UTC)."
        ),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(
            name="distinct_id",
            nullable=False,
            description="Identifier of the user/device the flag was evaluated for.",
        ),
        "created_at": DateTimeDatabaseField(
            name="created_at",
            nullable=False,
            description="When PostHog ingested the event (server timestamp); differs from `timestamp`.",
        ),
        "inserted_at": DateTimeDatabaseField(
            name="inserted_at",
            nullable=False,
            description="When the row was written to ClickHouse; later than `created_at` by the ingestion lag.",
        ),
        "person_id": UUIDDatabaseField(
            name="person_id",
            nullable=False,
            description="The person the evaluation was attributed to when it happened. A later identify or merge "
            "does not rewrite it, so it can differ from the person `events` resolves for the same `distinct_id`.",
        ),
        "flag_key": StringDatabaseField(
            name="flag_key",
            nullable=False,
            description="Key of the flag that was evaluated; the typed copy of `properties.$feature_flag`.",
        ),
        "response": StringDatabaseField(
            name="response",
            nullable=False,
            description="What the flag returned: 'true', 'false', or a variant key. A flag that returned JSON null "
            "stores the literal string 'null'.",
        ),
        "session_id": StringDatabaseField(
            name="session_id", nullable=False, description="Session the evaluation happened in, if the SDK sent one."
        ),
        "request_id": StringDatabaseField(
            name="request_id",
            nullable=False,
            description="Identifier of the flag-evaluation request, shared by every flag evaluated in it.",
        ),
        # Person columns on the row itself. Should not be used directly; reached via `person`.
        "poe": FlagEvaluationsPersonSubTable(),
        "person": FieldTraverser(
            chain=["poe"],
            description="The person the evaluation was attributed to when it happened. Access properties via "
            "`person.properties.*`.",
        ),
        # Group keys only. The row carries no group properties, so there is nothing to traverse to:
        # join to `groups` on one of these keys to read a group's current properties.
        "$group_0": StringDatabaseField(
            name="$group_0",
            nullable=False,
            description="Key of the type-0 group the evaluation was attributed to. Join to `groups` for its "
            "properties.",
        ),
        "$group_1": StringDatabaseField(name="$group_1", nullable=False, description="Key of the type-1 group."),
        "$group_2": StringDatabaseField(name="$group_2", nullable=False, description="Key of the type-2 group."),
        "$group_3": StringDatabaseField(name="$group_3", nullable=False, description="Key of the type-3 group."),
        "$group_4": StringDatabaseField(name="$group_4", nullable=False, description="Key of the type-4 group."),
    }

    def to_printed_clickhouse(self, context):
        return FLAG_EVALUATIONS_CLICKHOUSE_TABLE

    def to_printed_hogql(self):
        return FLAG_EVALUATIONS_CLICKHOUSE_TABLE
