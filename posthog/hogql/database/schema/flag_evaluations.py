from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.database.lazy_join_tags import GROUP_N, PERSON_DISTINCT_ID_OVERRIDES, PERSONS
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
from posthog.hogql.database.schema.util.uuid import uuid_string_expr_to_uint128_expr
from posthog.hogql.parser import parse_expr

from posthog.constants import GROUP_TYPES_LIMIT

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

# The physical read table is the Distributed `flag_evaluations` on the DATA nodes, defined in
# posthog/models/flag_evaluations/sql.py. That module imports django.conf, and
# posthog/hogql/test/test_no_django_imports.py imports this package with no django.setup(), so the
# name is spelled out here rather than imported.
FLAG_EVALUATIONS_CLICKHOUSE_TABLE = "flag_evaluations"


# The expression the events table uses under the persons-on-events modes that apply overrides. This table
# applies it for every team instead of following the mode, because the mode decides where person properties
# come from and this table stores none. A team on `PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS` therefore
# reads a merge-aware person here, and from `events` the write-time person until the squash rewrites it.
# The table and its `poe` subtable each take their own copy. The tests in test_flag_evaluations.py select
# `person_id` and `person.id` together, so the two drifting apart fails there.
def _person_id() -> ExpressionField:
    return ExpressionField(
        name="person_id",
        expr=parse_expr(
            # NOTE: assumes `join_use_nulls = 0` (the default), as ``override.distinct_id`` is not Nullable
            "if(not(empty(override.distinct_id)), override.person_id, flag_evaluation_person_id)",
            start=None,
        ),
        isolate_scope=True,
        description="The person the evaluation is attributed to, corrected for any later identify or merge, so "
        "`uniq(person_id)` counts a merged person once.",
    )


class FlagEvaluationsPersonSubTable(VirtualTable):
    """The person the flag-evaluation row resolves to, corrected by `person_distinct_id_overrides`.

    Narrower than EventsPersonSubTable, which also declares `person_created_at` and `properties` --
    columns this table does not store, so reusing it would let `person.created_at`,
    `person.properties` and `SELECT person.*` compile into a column the shards lack.
    """

    fields: dict[str, FieldOrTable] = {
        "id": _person_id(),
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
        # Left visible because it is the only person filter the `person_id_idx` bloom filter can serve,
        # and a hidden field reaches neither the schema browser nor `system.information_schema.columns`.
        "flag_evaluation_person_id": UUIDDatabaseField(
            name="person_id",
            nullable=False,
            description="The person written onto the row at ingestion time, before any later identify or "
            "merge. Unlike `person_id` it is a stored column, so filtering on it can use the table's index; "
            "it stays stale until the person-overrides squash rewrites it.",
        ),
        # Joined only when a query reads `person_id`, so every other query pays nothing for it. Hidden
        # because it is an implementation detail of that correction: it carries person columns the row
        # does not store, and `person` is the documented way to reach the person.
        "override": LazyJoin(
            from_field=["distinct_id"],
            join_table=PersonDistinctIdOverridesTable(),
            resolver=PERSON_DISTINCT_ID_OVERRIDES,
            hidden=True,
        ),
        "person_id": _person_id(),
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
        # Insight session math reads the events column name.
        "$session_id": ExpressionField(
            name="$session_id", expr=ast.Field(chain=["session_id"]), isolate_scope=True, hidden=True
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
            description="The person the evaluation is attributed to, corrected for any later identify or merge, so "
            "`uniq(person.id)` counts a merged person once. Carries the id alone: the row stores no person "
            "properties, so join to `persons` to read them.",
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

    def avoid_asterisk_fields(self) -> list[str]:
        # The stored person is a filtering escape hatch, not a second person column in `SELECT *`. Only the
        # asterisk reads this list, so the column stays in the schema browser and in `information_schema`.
        return ["flag_evaluation_person_id"]

    def to_printed_clickhouse(self, context):
        return FLAG_EVALUATIONS_CLICKHOUSE_TABLE

    def to_printed_hogql(self):
        return FLAG_EVALUATIONS_CLICKHOUSE_TABLE


# The fields add_events_list_fields_to_flag_evaluations adds that join another table.
EVENTS_LIST_JOINED_FIELDS = frozenset({"person", "session", *(f"group_{index}" for index in range(GROUP_TYPES_LIMIT))})


def add_events_list_fields_to_flag_evaluations(database: "Database") -> None:
    """Add the fields an events list reads to `posthog.flag_evaluations` in `database`, so a list query resolves there.

    This changes the table instance that `database` holds. Every later query compiled against `database` sees the wider
    table. Pass a database that only the events list runner uses, such as its `shared_database`.
    """
    flag_evaluations = database.get_table(["posthog", "flag_evaluations"])
    events_session = database.get_table("events").fields["session"]
    assert isinstance(events_session, LazyJoin)

    # This joins persons on the merge-corrected person_id, the way events does under
    # PERSON_ID_OVERRIDE_PROPERTIES_JOINED. The join is lazy. A query that reads no person field skips it.
    flag_evaluations.fields["person"] = LazyJoin(
        from_field=["person_id"], join_table=database.get_table("persons"), resolver=PERSONS
    )
    groups = database.get_table("groups")
    for index in range(GROUP_TYPES_LIMIT):
        flag_evaluations.fields[f"group_{index}"] = LazyJoin(
            from_field=[f"$group_{index}"], join_table=groups, resolver=GROUP_N, resolver_params={"group_index": index}
        )

    # The events session resolvers ignore from_field and read $session_id and $session_id_uuid from the source table.
    # Copying the events join keeps the sessions table version that the team's modifiers chose.
    flag_evaluations.fields["$session_id_uuid"] = ExpressionField(
        name="$session_id_uuid",
        expr=uuid_string_expr_to_uint128_expr(ast.Field(chain=["session_id"])),
        isolate_scope=True,
    )
    flag_evaluations.fields["session"] = events_session.model_copy()

    # The table stores no elements and no person mode. A flag call on events has no elements either.
    # An element filter therefore matches nothing on both tables. The empty array keeps its String element type.
    for name in ("elements_chain", "elements_chain_href", "person_mode"):
        flag_evaluations.fields[name] = ExpressionField(name=name, expr=ast.Constant(value=""))
    for name in ("elements_chain_texts", "elements_chain_ids", "elements_chain_elements"):
        flag_evaluations.fields[name] = ExpressionField(
            name=name,
            expr=ast.Call(name="arrayResize", args=[ast.Array(exprs=[ast.Constant(value="")]), ast.Constant(value=0)]),
        )
