from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

from posthog.models.person_group_membership.sql import PERSON_GROUP_MEMBERSHIP_TABLE


class PersonGroupMembershipTable(Table):
    description: str = (
        "Event-derived account associations. Aggregate first_seen and last_seen because parts merge lazily."
    )
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(
            name="team_id", nullable=False, description="Project that owns the association."
        ),
        "group_type_index": IntegerDatabaseField(
            name="group_type_index", nullable=False, description="Configured account group type index, from 0 to 4."
        ),
        "group_key": StringDatabaseField(name="group_key", nullable=False, description="Account external group key."),
        "distinct_id": StringDatabaseField(
            name="distinct_id",
            nullable=False,
            description="Event distinct ID. Resolve its current identity through person_distinct_ids.",
        ),
        "first_seen": DateTimeDatabaseField(
            name="first_seen",
            nullable=False,
            description="Earliest source event time in this part, in UTC. Read with min().",
        ),
        "last_seen": DateTimeDatabaseField(
            name="last_seen",
            nullable=False,
            description="Latest source event time in this part, in UTC. Read with max().",
        ),
    }

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return PERSON_GROUP_MEMBERSHIP_TABLE

    def to_printed_hogql(self) -> str:
        return "posthog.person_group_membership"
