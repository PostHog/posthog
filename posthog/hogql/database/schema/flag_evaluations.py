from posthog.hogql.database.lazy_join_tags import PERSON_DISTINCT_ID_OVERRIDES
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    ExpressionField,
    FieldOrTable,
    FieldTraverser,
    IntegerDatabaseField,
    LazyJoin,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    UUIDDatabaseField,
    VirtualTable,
)
from posthog.hogql.database.schema.person_distinct_id_overrides import PersonDistinctIdOverridesTable
from posthog.hogql.parser import parse_expr

# The physical read table is the Distributed `flag_evaluations` on the DATA nodes, defined in
# posthog/models/flag_evaluations/sql.py. That module imports django.conf, and
# posthog/hogql/test/test_no_django_imports.py imports this package with no django.setup(), so the
# name is spelled out here rather than imported.
FLAG_EVALUATIONS_CLICKHOUSE_TABLE = "flag_evaluations"


# The same expression the events table uses, so both tables resolve one distinct_id to the same person.
# The table and its `poe` subtable share this one field, so `person_id` and `person.id` cannot disagree.
_PERSON_ID = ExpressionField(
    name="person_id",
    expr=parse_expr(
        # NOTE: assumes `join_use_nulls = 0` (the default), as ``override.distinct_id`` is not Nullable
        "if(not(empty(override.distinct_id)), override.person_id, flag_evaluation_person_id)",
        start=None,
    ),
    isolate_scope=True,
    description="The person the evaluation is attributed to, corrected for any later identify or merge. The "
    "row keeps the person it was attributed to when it happened; that stored id is remapped at read time via "
    "`person_distinct_id_overrides`, so `uniq(person_id)` counts a merged human once.",
)


class FlagEvaluationsPersonSubTable(VirtualTable):
    """The person the flag-evaluation row resolves to, corrected by `person_distinct_id_overrides`.

    Narrower than EventsPersonSubTable, which also declares `person_created_at` and `properties` --
    columns this table does not store, so reusing it would let `person.created_at`,
    `person.properties` and `SELECT person.*` compile into a column the shards lack.
    """

    fields: dict[str, FieldOrTable] = {
        "id": _PERSON_ID,
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
        # The person written onto the row at ingestion time. Nothing rewrites it when a later identify or
        # merge joins that person to another, so it is hidden behind `person_id`, which corrects it.
        "flag_evaluation_person_id": UUIDDatabaseField(name="person_id", nullable=False, hidden=True),
        # Joined only when a query reads `person_id`, so every other query pays nothing for it.
        "override": LazyJoin(
            from_field=["distinct_id"],
            join_table=PersonDistinctIdOverridesTable(),
            resolver=PERSON_DISTINCT_ID_OVERRIDES,
        ),
        "person_id": _PERSON_ID,
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
        # Should not be used directly; reached via `person`.
        "poe": FlagEvaluationsPersonSubTable(),
        "person": FieldTraverser(
            chain=["poe"],
            description="The person the evaluation is attributed to, corrected for any later identify or merge. "
            "Carries the id alone: the row stores no person properties, so join to `persons` to read them.",
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
