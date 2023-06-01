from pydantic import BaseModel

from posthog.hogql.database.models import (
    VirtualTable,
    StringDatabaseField,
    DateTimeDatabaseField,
    StringJSONDatabaseField,
    IntegerDatabaseField,
    Table,
    LazyJoin,
    FieldTraverser,
)
from posthog.hogql.database.schema.person_distinct_ids import PersonDistinctIdTable, join_with_person_distinct_ids_table

from posthog.hogql.database.schema.person_overrides import PersonOverridesTable, join_with_person_overrides_table


class EventsPersonSubTable(VirtualTable):
    id: StringDatabaseField = StringDatabaseField(name="person_id")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="person_created_at")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="person_properties")

    def clickhouse_table(self):
        return "events"

    def hogql_table(self):
        return "events"


class EventsGroupSubTable(VirtualTable):
    key: StringDatabaseField
    created_at: DateTimeDatabaseField
    properties: StringJSONDatabaseField

    def __init__(self, group_index: int):
        super().__init__(
            key=StringDatabaseField(name=f"$group_{group_index}"),
            created_at=DateTimeDatabaseField(name=f"group{group_index}_created_at"),
            properties=StringJSONDatabaseField(name=f"group{group_index}_properties"),
        )

    def avoid_asterisk_fields(self):
        return []

    def clickhouse_table(self):
        return "events"

    def hogql_table(self):
        return "events"


class EventsTable(Table):
    uuid: StringDatabaseField = StringDatabaseField(name="uuid")
    event: StringDatabaseField = StringDatabaseField(name="event")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="properties")
    timestamp: DateTimeDatabaseField = DateTimeDatabaseField(name="timestamp")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    distinct_id: StringDatabaseField = StringDatabaseField(name="distinct_id")
    elements_chain: StringDatabaseField = StringDatabaseField(name="elements_chain")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")

    # Lazy table that adds a join to the persons table
    pdi: LazyJoin = LazyJoin(
        from_field="distinct_id",
        join_table=PersonDistinctIdTable(),
        join_function=join_with_person_distinct_ids_table,
    )

    # Lazy table to fetch the overridden person_id
    override: LazyJoin = LazyJoin(
        from_field="person_id",
        join_table=PersonOverridesTable(),
        join_function=join_with_person_overrides_table,
    )
    override_person_id: BaseModel = FieldTraverser(chain=["override", "override_person_id"])

    # Person and group fields on the event itself. Should not be used directly.
    poe: EventsPersonSubTable = EventsPersonSubTable()
    goe_0: EventsGroupSubTable = EventsGroupSubTable(group_index=0)
    goe_1: EventsGroupSubTable = EventsGroupSubTable(group_index=1)
    goe_2: EventsGroupSubTable = EventsGroupSubTable(group_index=2)
    goe_3: EventsGroupSubTable = EventsGroupSubTable(group_index=3)
    goe_4: EventsGroupSubTable = EventsGroupSubTable(group_index=4)

    # These are swapped out if the user has PoE enabled
    person: BaseModel = FieldTraverser(chain=["pdi", "person"])
    person_id: BaseModel = FieldTraverser(chain=["pdi", "person_id"])

    def clickhouse_table(self):
        return "events"

    def hogql_table(self):
        return "events"
