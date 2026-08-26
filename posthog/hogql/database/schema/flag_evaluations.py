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


class FlagEvaluationsGroupSubTable(VirtualTable):
    """Group columns carried on the flag-evaluation row itself."""

    group_index: int = 0

    def __init__(self, group_index: int):
        super().__init__(
            fields={
                "key": StringDatabaseField(name=f"$group_{group_index}", nullable=False),
                "properties": StringJSONDatabaseField(name=f"group{group_index}_properties", nullable=False),
            }
        )
        self.group_index = group_index

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
        # Person and group columns on the row itself. Should not be used directly; reached via
        # `person` and `group_0`..`group_4`.
        "poe": FlagEvaluationsPersonSubTable(),
        "goe_0": FlagEvaluationsGroupSubTable(group_index=0),
        "goe_1": FlagEvaluationsGroupSubTable(group_index=1),
        "goe_2": FlagEvaluationsGroupSubTable(group_index=2),
        "goe_3": FlagEvaluationsGroupSubTable(group_index=3),
        "goe_4": FlagEvaluationsGroupSubTable(group_index=4),
        "person": FieldTraverser(
            chain=["poe"],
            description="The person the evaluation was attributed to when it happened. Access properties via "
            "`person.properties.*`.",
        ),
        "$group_0": StringDatabaseField(name="$group_0", nullable=False),
        "$group_1": StringDatabaseField(name="$group_1", nullable=False),
        "$group_2": StringDatabaseField(name="$group_2", nullable=False),
        "$group_3": StringDatabaseField(name="$group_3", nullable=False),
        "$group_4": StringDatabaseField(name="$group_4", nullable=False),
        # Group properties come from the row, not from a join to `groups`. join_with_group_n_table's
        # prefilter only bounds the groups side when the outer FROM is literally `events`, so a join
        # here would read every group of that type for the team.
        "group_0": FieldTraverser(
            chain=["goe_0"],
            description="Group of type 0 the evaluation was attributed to, with the properties it had at the time. "
            "Access them via `group_0.properties.*`.",
        ),
        "group_1": FieldTraverser(chain=["goe_1"], description="Group of type 1, as captured at evaluation time."),
        "group_2": FieldTraverser(chain=["goe_2"], description="Group of type 2, as captured at evaluation time."),
        "group_3": FieldTraverser(chain=["goe_3"], description="Group of type 3, as captured at evaluation time."),
        "group_4": FieldTraverser(chain=["goe_4"], description="Group of type 4, as captured at evaluation time."),
    }

    def to_printed_clickhouse(self, context):
        return FLAG_EVALUATIONS_CLICKHOUSE_TABLE

    def to_printed_hogql(self):
        return FLAG_EVALUATIONS_CLICKHOUSE_TABLE
