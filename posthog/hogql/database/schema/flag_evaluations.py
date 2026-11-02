from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.database.lazy_join_tags import GROUP_N, PERSON_DISTINCT_ID_OVERRIDES, PERSON_DISTINCT_IDS, PERSONS
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
from posthog.hogql.database.schema.person_distinct_ids import PersonDistinctIdsTable
from posthog.hogql.database.schema.util.null_sentinels import null_if_sentinels
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

# Keep it equal to FLAG_EVALUATIONS_TABLE in frontend/src/scenes/feature-flags/flagEvaluationsTable.ts.
FLAG_EVALUATIONS_HOGQL_TABLE = "posthog.flag_evaluations"


# The expression the events table uses under the persons-on-events modes that apply overrides. This table
# applies it for every team instead of following the mode, because the mode decides where person properties
# come from and this table does not follow the mode for those either. A team on
# `PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS` therefore reads a merge-aware person here, and from `events` the
# write-time person until the squash rewrites it.
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

    `properties` and `created_at` read the columns stored at evaluation time, as events does under
    persons-on-events. EventsPersonSubTable does not fit, because its `id` reads the stored person and
    the printer treats it as part of `events`.
    """

    fields: dict[str, FieldOrTable] = {
        "id": _person_id(),
        "created_at": DateTimeDatabaseField(name="person_created_at", nullable=False),
        "properties": StringJSONDatabaseField(name="person_properties", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return FLAG_EVALUATIONS_CLICKHOUSE_TABLE

    def to_printed_hogql(self):
        return FLAG_EVALUATIONS_CLICKHOUSE_TABLE


class FlagEvaluationsGroupKeySubTable(VirtualTable):
    """`goe_N` on events, limited to the group key. The row stores no group properties or creation time at
    evaluation time, so `goe_N.properties` and `goe_N.created_at` do not resolve here."""

    def __init__(self, group_index: int):
        super().__init__(
            fields={
                "key": ExpressionField(
                    name="key", expr=ast.Field(chain=[f"_$group_{group_index}_raw"]), isolate_scope=True
                )
            }
        )

    def to_printed_clickhouse(self, context):
        return FLAG_EVALUATIONS_CLICKHOUSE_TABLE

    def to_printed_hogql(self):
        return FLAG_EVALUATIONS_CLICKHOUSE_TABLE


# The events element columns that this table defines as constants, grouped by the type of the constant.
_ELEMENT_STRING_STAND_INS = ("elements_chain", "elements_chain_href")
_ELEMENT_ARRAY_STAND_INS = ("elements_chain_texts", "elements_chain_ids", "elements_chain_elements")
ELEMENT_STAND_INS = frozenset(_ELEMENT_STRING_STAND_INS + _ELEMENT_ARRAY_STAND_INS)


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
            "where they cover what you need: reading the same value out of this JSON scans far more data. "
            "A property that holds an empty string reads as '' here, where `events` can return NULL. A value with "
            "an escaped character, such as a quote, can also read differently than on `events`.",
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
        # `flag_key` is in the sort key, and `session_id` and `request_id` carry bloom filters. They stay bare because
        # a `nullIf` wrap stops a filter from using either. `$group_0`..`$group_4` keep '' as the events columns do.
        "flag_evaluation_response": StringDatabaseField(name="response", nullable=False, hidden=True),
        "response": ExpressionField(
            name="response",
            expr=null_if_sentinels(ast.Field(chain=["flag_evaluation_response"])),
            isolate_scope=True,
            nullable=True,
            description="What the flag returned: 'true', 'false', or a variant key. NULL when the flag returned null "
            "or the SDK sent no response, as on events. A variant named 'null' also reads NULL. "
            "`JSONHas(properties, '$feature_flag_response')` tells a null response from a missing one.",
        ),
        "session_id": StringDatabaseField(
            name="session_id", nullable=False, description="Session the evaluation happened in, if the SDK sent one."
        ),
        # Insight session math reads the events column name.
        "$session_id": ExpressionField(
            name="$session_id", expr=ast.Field(chain=["session_id"]), isolate_scope=True, hidden=True
        ),
        # The sessions join that database.py copies from events reads $session_id and $session_id_uuid from here.
        "$session_id_uuid": ExpressionField(
            name="$session_id_uuid",
            expr=uuid_string_expr_to_uint128_expr(ast.Field(chain=["session_id"])),
            isolate_scope=True,
            hidden=True,
        ),
        "request_id": StringDatabaseField(
            name="request_id",
            nullable=False,
            description="Identifier of the flag-evaluation request, shared by every flag evaluated in it.",
        ),
        "person_mode": StringDatabaseField(
            name="person_mode",
            nullable=False,
            description="How ingestion processed the person: 'full', 'propertyless' or 'force_upgrade'. A "
            "'propertyless' evaluation had no person profile, and its `person.properties` is '{}'.",
        ),
        # Should not be used directly; reached via `person`.
        "poe": FlagEvaluationsPersonSubTable(),
        "person": FieldTraverser(
            chain=["poe"],
            description="The person the evaluation is attributed to. `person.id` is corrected for any later identify "
            "or merge, so `uniq(person.id)` counts a merged person once. `person.properties` and `person.created_at` "
            "are the values stored at evaluation time, not the person's current ones.",
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
        # The stored keys, which goe_N.key reads, as events reads goe_N.key from its stored column. A team's group
        # type mappings can replace $group_N with a key that is empty for calls from before the mapping existed.
        **{
            f"_$group_{index}_raw": StringDatabaseField(name=f"$group_{index}", nullable=False, hidden=True)
            for index in range(GROUP_TYPES_LIMIT)
        },
        # A group property filter, such as a team's test account filter, compiles to `group_N.properties`.
        # These joins let it resolve here as it does on events.
        **{
            f"group_{index}": LazyJoin(
                from_field=[f"$group_{index}"],
                join_table="groups",
                resolver=GROUP_N,
                resolver_params={"group_index": index},
                hidden=True,
            )
            for index in range(GROUP_TYPES_LIMIT)
        },
        # The events names below let a query on events that reads flag calls resolve here when HogQL swaps the table.
        "$window_id": ExpressionField(
            name="$window_id",
            expr=ast.Call(name="ifNull", args=[ast.Field(chain=["properties", "$window_id"]), ast.Constant(value="")]),
            isolate_scope=True,
            hidden=True,
        ),
        "event_person_id": UUIDDatabaseField(name="person_id", hidden=True),
        "pdi": LazyJoin(
            from_field=["distinct_id"],
            join_table=PersonDistinctIdsTable(),
            resolver=PERSON_DISTINCT_IDS,
            hidden=True,
        ),
        **{f"goe_{index}": FlagEvaluationsGroupKeySubTable(group_index=index) for index in range(GROUP_TYPES_LIMIT)},
        # The table stores no elements, and a flag call on events has none either. An element filter therefore
        # resolves here and matches nothing, as it does on events. The empty array keeps its String element type.
        **{
            name: ExpressionField(name=name, expr=ast.Constant(value=""), hidden=True)
            for name in _ELEMENT_STRING_STAND_INS
        },
        **{
            name: ExpressionField(
                name=name,
                expr=ast.Call(
                    name="arrayResize", args=[ast.Array(exprs=[ast.Constant(value="")]), ast.Constant(value=0)]
                ),
                hidden=True,
            )
            for name in _ELEMENT_ARRAY_STAND_INS
        },
    }

    def avoid_asterisk_fields(self) -> list[str]:
        # The stored person is a filtering escape hatch, not a second person column in `SELECT *`. Only the
        # asterisk reads this list, so the column stays in the schema browser and in `information_schema`.
        return ["flag_evaluation_person_id"]

    def to_printed_clickhouse(self, context):
        return FLAG_EVALUATIONS_CLICKHOUSE_TABLE

    def to_printed_hogql(self):
        return FLAG_EVALUATIONS_CLICKHOUSE_TABLE


# The fields an events list reads from flag_evaluations that join another table.
EVENTS_LIST_JOINED_FIELDS = frozenset({"person", "session", *(f"group_{index}" for index in range(GROUP_TYPES_LIMIT))})


def add_events_list_fields_to_flag_evaluations(database: "Database") -> None:
    """Make `person` on `posthog.flag_evaluations` in `database` a persons join, as an events list reads it.

    This changes the table instance that `database` holds. Every later query compiled against `database` reads each
    person's current properties instead of the stored ones. Pass a database that only the events list runner uses,
    such as its `shared_database`.
    """
    flag_evaluations = database.get_table(["posthog", "flag_evaluations"])

    # This joins persons on the merge-corrected person_id, the way events does under
    # PERSON_ID_OVERRIDE_PROPERTIES_JOINED. The join is lazy. A query that reads no person field skips it.
    flag_evaluations.fields["person"] = LazyJoin(
        from_field=["person_id"], join_table=database.get_table("persons"), resolver=PERSONS
    )
