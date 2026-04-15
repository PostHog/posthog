from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    FieldTraverser,
    IntegerDatabaseField,
    LazyJoin,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)
from posthog.hogql.database.schema.person_distinct_ids import (
    PersonDistinctIdsTable,
    join_with_person_distinct_ids_table,
)


class FeatureFlagCallDebugTable(Table):
    fields: dict[str, FieldOrTable] = {
        "uuid": StringDatabaseField(name="uuid", nullable=False),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
        "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
        "person_id": StringDatabaseField(name="person_id", nullable=False),
        "flag_key": StringDatabaseField(name="flag_key", nullable=False),
        "properties": StringJSONDatabaseField(name="properties", nullable=False),
        "pdi": LazyJoin(
            from_field=["distinct_id"],
            join_table=PersonDistinctIdsTable(),
            join_function=join_with_person_distinct_ids_table,
        ),
        "person": FieldTraverser(chain=["pdi", "person"]),
    }

    def to_printed_clickhouse(self, context):
        return "feature_flag_call_debug"

    def to_printed_hogql(self):
        return "feature_flag_call_debug"
