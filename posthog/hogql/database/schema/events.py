from typing import Dict

from posthog.hogql.database.models import (
    VirtualTable,
    StringDatabaseField,
    DateTimeDatabaseField,
    StringJSONDatabaseField,
    IntegerDatabaseField,
    Table,
    LazyJoin,
    FieldTraverser,
    FieldOrTable,
)
from posthog.hogql.database.schema.person_distinct_ids import (
    PersonDistinctIdsTable,
    join_with_person_distinct_ids_table,
)
from posthog.hogql.database.schema.person_overrides import PersonOverridesTable, join_with_person_overrides_table


class EventsPersonSubTable(VirtualTable):
    fields: Dict[str, FieldOrTable] = {
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


class EventsTable(Table):
    fields: Dict[str, FieldOrTable] = {
        "uuid": StringDatabaseField(name="uuid"),
        "event": StringDatabaseField(name="event"),
        "properties": StringJSONDatabaseField(name="properties"),
        "timestamp": DateTimeDatabaseField(name="timestamp"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "distinct_id": StringDatabaseField(name="distinct_id"),
        "elements_chain": StringDatabaseField(name="elements_chain"),
        "created_at": DateTimeDatabaseField(name="created_at"),
        # Lazy table that adds a join to the persons table
        "pdi": LazyJoin(
            from_field="distinct_id",
            join_table=PersonDistinctIdsTable(),
            join_function=join_with_person_distinct_ids_table,
        ),
        # Lazy table to fetch the overridden person_id
        "override": LazyJoin(
            from_field="person_id",
            join_table=PersonOverridesTable(),
            join_function=join_with_person_overrides_table,
        ),
        "override_person_id": FieldTraverser(chain=["override", "override_person_id"]),
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
    }

    def to_printed_clickhouse(self, context):
        return "events"

    def to_printed_hogql(self):
        return "events"
