from posthog.hogql.database.lazy_join_tags import (
    EVENTS_TO_SESSIONS_V1,
    GROUP_N,
    PERSON_DISTINCT_IDS,
    PERSONS_REVENUE_ANALYTICS,
)
from posthog.hogql.database.models import (
    DatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FieldTraverser,
    IntegerDatabaseField,
    LazyJoin,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    VirtualTable,
)
from posthog.hogql.database.schema.groups import GroupsTable
from posthog.hogql.database.schema.person_distinct_ids import PersonDistinctIdsTable
from posthog.hogql.database.schema.persons_revenue_analytics import PersonsRevenueAnalyticsTable
from posthog.hogql.database.schema.sessions_v1 import SessionsTableV1


class EventsPersonSubTable(VirtualTable):
    fields: dict[str, FieldOrTable] = {
        "id": StringDatabaseField(name="person_id", nullable=False),
        "created_at": DateTimeDatabaseField(name="person_created_at", nullable=False),
        "properties": StringJSONDatabaseField(name="person_properties", nullable=False),
        "revenue_analytics": LazyJoin(
            from_field=["person_id"],
            join_table=PersonsRevenueAnalyticsTable(),
            resolver=PERSONS_REVENUE_ANALYTICS,
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
                "key": StringDatabaseField(name=f"$group_{group_index}", nullable=False),
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
    description: str = "Every analytics event captured for the project. The central fact table for product analytics."
    fields: dict[str, FieldOrTable] = {
        "uuid": StringDatabaseField(name="uuid", nullable=False, description="Unique identifier of this event row."),
        "event": StringDatabaseField(
            name="event",
            nullable=False,
            description="Event name, e.g. '$pageview' or 'purchase'. Autocapture/PostHog events are prefixed with '$'.",
        ),
        "properties": StringJSONDatabaseField(
            name="properties",
            nullable=False,
            description="JSON map of event properties. Access nested keys with `properties.$browser` etc.",
        ),
        "timestamp": DateTimeDatabaseField(
            name="timestamp", nullable=False, description="When the event occurred (client timestamp, in UTC)."
        ),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(
            name="distinct_id",
            nullable=False,
            description="Identifier of the user/device that sent the event; resolved to a person via `person_id`.",
        ),
        "elements_chain": StringDatabaseField(
            name="elements_chain",
            nullable=False,
            description="Serialized DOM element chain for autocapture events; usually parsed via the `elements` helpers.",
        ),
        "created_at": DateTimeDatabaseField(
            name="created_at",
            nullable=False,
            description="When the event was ingested by PostHog (server timestamp); differs from `timestamp`.",
        ),
        "$session_id": StringDatabaseField(
            name="$session_id", nullable=False, description="Session this event belongs to; join to `sessions`."
        ),
        "$session_id_uuid": DatabaseField(name="$session_id_uuid", nullable=False),
        "$window_id": StringDatabaseField(
            name="$window_id", nullable=False, description="Window/tab identifier within a session."
        ),
        "person_mode": StringDatabaseField(name="person_mode", nullable=False),
        # Lazy table that adds a join to the persons table
        "pdi": LazyJoin(
            from_field=["distinct_id"],
            join_table=PersonDistinctIdsTable(),
            resolver=PERSON_DISTINCT_IDS,
        ),
        # Person and group fields on the event itself. Should not be used directly.
        "poe": EventsPersonSubTable(),
        "goe_0": EventsGroupSubTable(group_index=0),
        "goe_1": EventsGroupSubTable(group_index=1),
        "goe_2": EventsGroupSubTable(group_index=2),
        "goe_3": EventsGroupSubTable(group_index=3),
        "goe_4": EventsGroupSubTable(group_index=4),
        # These are swapped out if the user has PoE enabled
        "person": FieldTraverser(
            chain=["pdi", "person"],
            description="The person this event is attributed to. Access person properties via `person.properties.*`.",
        ),
        "person_id": FieldTraverser(
            chain=["pdi", "person_id"], description="Stable person identifier resolved from `distinct_id`."
        ),
        "$group_0": StringDatabaseField(name="$group_0", nullable=False),
        "group_0": LazyJoin(
            from_field=["$group_0"],
            join_table=GroupsTable(),
            resolver=GROUP_N,
            resolver_params={"group_index": 0},
        ),
        "$group_1": StringDatabaseField(name="$group_1", nullable=False),
        "group_1": LazyJoin(
            from_field=["$group_1"],
            join_table=GroupsTable(),
            resolver=GROUP_N,
            resolver_params={"group_index": 1},
        ),
        "$group_2": StringDatabaseField(name="$group_2", nullable=False),
        "group_2": LazyJoin(
            from_field=["$group_2"],
            join_table=GroupsTable(),
            resolver=GROUP_N,
            resolver_params={"group_index": 2},
        ),
        "$group_3": StringDatabaseField(name="$group_3", nullable=False),
        "group_3": LazyJoin(
            from_field=["$group_3"],
            join_table=GroupsTable(),
            resolver=GROUP_N,
            resolver_params={"group_index": 3},
        ),
        "$group_4": StringDatabaseField(name="$group_4", nullable=False),
        "group_4": LazyJoin(
            from_field=["$group_4"],
            join_table=GroupsTable(),
            resolver=GROUP_N,
            resolver_params={"group_index": 4},
        ),
        "session": LazyJoin(
            from_field=["$session_id"],
            join_table=SessionsTableV1(),
            resolver=EVENTS_TO_SESSIONS_V1,
        ),
        "elements_chain_href": StringDatabaseField(name="elements_chain_href", nullable=False),
        "elements_chain_texts": StringArrayDatabaseField(name="elements_chain_texts", nullable=False),
        "elements_chain_ids": StringArrayDatabaseField(name="elements_chain_ids", nullable=False),
        "elements_chain_elements": StringArrayDatabaseField(name="elements_chain_elements", nullable=False),
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
