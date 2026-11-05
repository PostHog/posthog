from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)


class PersonGroupMembershipTable(Table):
    description: str = (
        "Historical distinct-ID membership in groups. Resolve current persons through person_distinct_ids."
    )
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(
            name="team_id", nullable=False, description="Project that owns the membership."
        ),
        "group_type_index": IntegerDatabaseField(
            name="group_type_index", nullable=False, description="Configured account group type index, from 0 to 4."
        ),
        "group_key": StringDatabaseField(
            name="group_key", nullable=False, description="External group key of the account."
        ),
        "distinct_id": StringDatabaseField(
            name="distinct_id",
            nullable=False,
            description="Event distinct ID. Join to person_distinct_ids.distinct_id.",
        ),
        "first_seen": DateTimeDatabaseField(
            name="first_seen", nullable=False, description="Earliest account event for this distinct ID, in UTC."
        ),
        "last_seen": DateTimeDatabaseField(
            name="last_seen", nullable=False, description="Latest account event for this distinct ID, in UTC."
        ),
    }

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return "person_group_membership"

    def to_printed_hogql(self) -> str:
        return "posthog.person_group_membership"
