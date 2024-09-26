from typing import Any

from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    VirtualTable,
    StringDatabaseField,
    DateTimeDatabaseField,
    StringJSONDatabaseField,
    StringArrayDatabaseField,
    IntegerDatabaseField,
    Table,
    LazyJoin,
    FieldTraverser,
    FieldOrTable,
    LazyTable,
    LazyTableToAdd,
)
from posthog.hogql.database.schema.groups import GroupsTable, join_with_group_n_table
from posthog.hogql.database.schema.person_distinct_ids import (
    PersonDistinctIdsTable,
    lazy_join_with_person_distinct_ids_table,
)
from posthog.hogql.database.schema.sessions_v1 import join_events_table_to_sessions_table, SessionsTableV1
from posthog.hogql.database.schema.util.where_clause_extractor import WhereClauseExtractor


class EventsPersonSubTable(VirtualTable):
    fields: dict[str, FieldOrTable] = {
        "id": StringDatabaseField(name="person_id"),
        "created_at": DateTimeDatabaseField(name="person_created_at"),
        "properties": StringJSONDatabaseField(name="person_properties"),
    }

    def to_printed_clickhouse(self, context):
        return "events"

    def to_printed_hogql(self):
        return "events"


class EventsGroupSubTable(VirtualTable):
    def __init__(self, group_index: int):
        super().__init__(
            fields={
                "key": StringDatabaseField(name=f"$group_{group_index}"),
                "created_at": DateTimeDatabaseField(name=f"group{group_index}_created_at"),
                "properties": StringJSONDatabaseField(name=f"group{group_index}_properties"),
            }
        )

    def avoid_asterisk_fields(self):
        return []

    def to_printed_clickhouse(self, context):
        return "events"

    def to_printed_hogql(self):
        return "events"


class EventsLazy(LazyTable):
    """
    A table that is replaced with a subquery returned from `lazy_select(requested_fields: Dict[name, chain], modifiers: HogQLQueryModifiers, node: SelectQuery)`
    """

    fields: dict[str, FieldOrTable] = {
        "uuid": StringDatabaseField(name="uuid"),
        "event": StringDatabaseField(name="event"),
        "properties": StringJSONDatabaseField(name="properties"),
        "timestamp": DateTimeDatabaseField(name="timestamp"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "distinct_id": StringDatabaseField(name="distinct_id"),
        "elements_chain": StringDatabaseField(name="elements_chain"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        "$session_id": StringDatabaseField(name="$session_id"),
        "$window_id": StringDatabaseField(name="$window_id"),
        # Lazy table that adds a join to the persons table
        "pdi": LazyJoin(
            from_field=["distinct_id"],
            join_table=PersonDistinctIdsTable(),
            join_function=lazy_join_with_person_distinct_ids_table,
        ),
        # Person and group fields on the event itself. Should not be used directly.
        "poe": EventsPersonSubTable(),
        "goe_0": EventsGroupSubTable(group_index=0),
        "goe_1": EventsGroupSubTable(group_index=1),
        "goe_2": EventsGroupSubTable(group_index=2),
        "goe_3": EventsGroupSubTable(group_index=3),
        "goe_4": EventsGroupSubTable(group_index=4),
        # These are swapped out if the user has PoE enabled
        "person": FieldTraverser(chain=["pdi", "person"]),
        "person_id": FieldTraverser(chain=["pdi", "person_id"]),
        "$group_0": StringDatabaseField(name="$group_0"),
        "group_0": LazyJoin(
            from_field=["$group_0"],
            join_table=GroupsTable(),
            join_function=join_with_group_n_table(0),
        ),
        "$group_1": StringDatabaseField(name="$group_1"),
        "group_1": LazyJoin(
            from_field=["$group_1"],
            join_table=GroupsTable(),
            join_function=join_with_group_n_table(1),
        ),
        "$group_2": StringDatabaseField(name="$group_2"),
        "group_2": LazyJoin(
            from_field=["$group_2"],
            join_table=GroupsTable(),
            join_function=join_with_group_n_table(2),
        ),
        "$group_3": StringDatabaseField(name="$group_3"),
        "group_3": LazyJoin(
            from_field=["$group_3"],
            join_table=GroupsTable(),
            join_function=join_with_group_n_table(3),
        ),
        "$group_4": StringDatabaseField(name="$group_4"),
        "group_4": LazyJoin(
            from_field=["$group_4"],
            join_table=GroupsTable(),
            join_function=join_with_group_n_table(4),
        ),
        "session": LazyJoin(
            from_field=["$session_id"],
            join_table=SessionsTableV1(),
            join_function=join_events_table_to_sessions_table,
        ),
        "elements_chain_href": StringDatabaseField(name="elements_chain_href"),
        "elements_chain_texts": StringArrayDatabaseField(name="elements_chain_texts"),
        "elements_chain_ids": StringArrayDatabaseField(name="elements_chain_ids"),
        "elements_chain_elements": StringArrayDatabaseField(name="elements_chain_elements"),
    }

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context: HogQLContext,
        node: SelectQuery,
    ) -> Any:
        select_fields: list[ast.Expr] = []
        for name, chain in table_to_add.fields_accessed.items():
            select_fields.append(ast.Alias(alias=name, expr=ast.Field(chain=["raw_events", *chain])))

        extractor = WhereClauseExtractor(context)
        extractor.add_local_tables(table_to_add)
        where = extractor.get_inner_where(node)
        return ast.SelectQuery(
            select=select_fields, select_from=ast.JoinExpr(table=ast.Field(chain=["raw_events"])), where=where
        )

    def to_printed_clickhouse(self, context):
        return "events_lazy"

    def to_printed_hogql(self):
        return "events"


REAL_FIELDS = {
    "uuid": StringDatabaseField(name="uuid"),
    "event": StringDatabaseField(name="event"),
    "properties": StringJSONDatabaseField(name="properties"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "distinct_id": StringDatabaseField(name="distinct_id"),
    "elements_chain": StringDatabaseField(name="elements_chain"),
    "created_at": DateTimeDatabaseField(name="created_at"),
    "$session_id": StringDatabaseField(name="$session_id"),
    "$window_id": StringDatabaseField(name="$window_id"),
    "person_id": StringDatabaseField(name="person_id"),
    "event_person_id": StringDatabaseField(name="person_id"),
    "$group_0": StringDatabaseField(name="$group_0"),
    "$group_1": StringDatabaseField(name="$group_1"),
    "$group_2": StringDatabaseField(name="$group_2"),
    "$group_3": StringDatabaseField(name="$group_3"),
    "$group_4": StringDatabaseField(name="$group_4"),
    "elements_chain_href": StringDatabaseField(name="elements_chain_href"),
    "elements_chain_texts": StringArrayDatabaseField(name="elements_chain_texts"),
    "elements_chain_ids": StringArrayDatabaseField(name="elements_chain_ids"),
    "elements_chain_elements": StringArrayDatabaseField(name="elements_chain_elements"),
}


class EventsTable(Table):
    fields: dict[str, FieldOrTable] = REAL_FIELDS

    def to_printed_clickhouse(self, context):
        return "events"

    def to_printed_hogql(self):
        return "raw_events"
