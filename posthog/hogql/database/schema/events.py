from posthog.hogql import ast
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
    VirtualTable,
)
from posthog.hogql.database.schema.groups import GroupsTable, join_with_group_n_table
from posthog.hogql.database.schema.person_distinct_ids import (
    PersonDistinctIdsTable,
    join_with_person_distinct_ids_table,
)
from posthog.hogql.database.schema.persons_revenue_analytics import (
    PersonsRevenueAnalyticsTable,
    join_with_persons_revenue_analytics_table,
)
from posthog.hogql.database.schema.sessions_v1 import SessionsTableV1, join_events_table_to_sessions_table


def event_property_field(name: str, property_name: str | None = None) -> ExpressionField:
    return ExpressionField(
        name=name,
        expr=ast.Field(chain=["properties", property_name or name]),
        isolate_scope=True,
        nullable=False,
    )


def session_id_uuid_field() -> ExpressionField:
    return ExpressionField(
        name="$session_id_uuid",
        expr=ast.Call(
            name="_toUInt128",
            args=[
                ast.Call(
                    name="_toUUIDOrNull",
                    args=[ast.Field(chain=["properties", "$session_id"])],
                )
            ],
        ),
        isolate_scope=True,
        nullable=False,
    )


def elements_chain_field(name: str, expr: ast.Expr) -> ExpressionField:
    return ExpressionField(name=name, expr=expr, isolate_scope=True, nullable=False)


def elements_chain_extract(pattern: str) -> ast.Call:
    return ast.Call(name="extract", args=[ast.Field(chain=["elements_chain"]), ast.Constant(value=pattern)])


def elements_chain_extract_all(pattern: str) -> ast.Call:
    return ast.Call(
        name="arrayDistinct",
        args=[
            ast.Call(
                name="extractAll",
                args=[ast.Field(chain=["elements_chain"]), ast.Constant(value=pattern)],
            )
        ],
    )


class EventsPersonSubTable(VirtualTable):
    fields: dict[str, FieldOrTable] = {
        "id": StringDatabaseField(name="person_id", nullable=False),
        "created_at": DateTimeDatabaseField(name="person_created_at", nullable=False),
        "properties": StringJSONDatabaseField(name="person_properties", nullable=False),
        "revenue_analytics": LazyJoin(
            from_field=["person_id"],
            join_table=PersonsRevenueAnalyticsTable(),
            join_function=join_with_persons_revenue_analytics_table,
        ),
    }

    def to_printed_clickhouse(self, context):
        return "events"

    def to_printed_hogql(self):
        return "events"


class EventsGroupSubTable(VirtualTable):
    def __init__(self, group_index: int):
        super().__init__(
            fields={
                "key": event_property_field("key", f"$group_{group_index}"),
                "created_at": DateTimeDatabaseField(name=f"group{group_index}_created_at", nullable=False),
                "properties": StringJSONDatabaseField(name=f"group{group_index}_properties", nullable=False),
            }
        )

    def avoid_asterisk_fields(self):
        return []

    def to_printed_clickhouse(self, context):
        return "events"

    def to_printed_hogql(self):
        return "events"


class EventsTable(Table):
    fields: dict[str, FieldOrTable] = {
        "uuid": StringDatabaseField(name="uuid", nullable=False),
        "event": StringDatabaseField(name="event", nullable=False),
        "properties": StringJSONDatabaseField(name="properties", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
        "elements_chain": StringDatabaseField(name="elements_chain", nullable=False),
        "created_at": DateTimeDatabaseField(name="created_at", nullable=False),
        "$session_id": event_property_field("$session_id"),
        "$session_id_uuid": session_id_uuid_field(),
        "$window_id": event_property_field("$window_id"),
        "person_mode": StringDatabaseField(name="person_mode", nullable=False),
        # Lazy table that adds a join to the persons table
        "pdi": LazyJoin(
            from_field=["distinct_id"],
            join_table=PersonDistinctIdsTable(),
            join_function=join_with_person_distinct_ids_table,
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
        "$group_0": event_property_field("$group_0"),
        "group_0": LazyJoin(
            from_field=["$group_0"],
            join_table=GroupsTable(),
            join_function=join_with_group_n_table(0),
        ),
        "$group_1": event_property_field("$group_1"),
        "group_1": LazyJoin(
            from_field=["$group_1"],
            join_table=GroupsTable(),
            join_function=join_with_group_n_table(1),
        ),
        "$group_2": event_property_field("$group_2"),
        "group_2": LazyJoin(
            from_field=["$group_2"],
            join_table=GroupsTable(),
            join_function=join_with_group_n_table(2),
        ),
        "$group_3": event_property_field("$group_3"),
        "group_3": LazyJoin(
            from_field=["$group_3"],
            join_table=GroupsTable(),
            join_function=join_with_group_n_table(3),
        ),
        "$group_4": event_property_field("$group_4"),
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
        "elements_chain_href": elements_chain_field(
            "elements_chain_href",
            elements_chain_extract(r'(?::|\")href="(.*?)"'),
        ),
        "elements_chain_texts": elements_chain_field(
            "elements_chain_texts",
            elements_chain_extract_all(r'(?::|\")text="(.*?)"'),
        ),
        "elements_chain_ids": elements_chain_field(
            "elements_chain_ids",
            elements_chain_extract_all(r'(?::|\")attr_id="(.*?)"'),
        ),
        "elements_chain_elements": elements_chain_field(
            "elements_chain_elements",
            elements_chain_extract_all(r"(?:^|;)(a|button|form|input|select|textarea|label)(?:\.|$|:)"),
        ),
    }

    def to_printed_clickhouse(self, context):
        return "events"

    def to_printed_hogql(self):
        return "events"

    def avoid_asterisk_fields(self) -> list[str]:
        return [
            "$session_id_uuid",
            "$virt_is_bot",
            "$virt_traffic_type",
            "$virt_traffic_category",
            "$virt_bot_name",
            "$virt_bot_operator",
        ]


# All table types that represent the events table (including virtual subtables like poe/goe).
# Use in isinstance() checks when you need to match any events-family table.
EVENTS_TABLE_TYPES = (EventsTable, EventsPersonSubTable, EventsGroupSubTable)
