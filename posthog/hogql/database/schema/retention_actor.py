from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
    UnknownDatabaseField,
    UUIDDatabaseField,
)

from posthog.clickhouse.preaggregation.retention_actor_sql import DISTRIBUTED_RETENTION_ACTOR_TABLE


class RetentionActorTable(Table):
    # `load_balancing="in_order"` so reads land on the replica a materialisation just wrote (read-your-writes).
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order")
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "kind": StringDatabaseField(name="kind"),
        "actor_id": UUIDDatabaseField(name="actor_id"),
        # AggregateFunction state columns — opaque to HogQL; read via minMerge / groupUniqArrayMerge.
        "first_seen": UnknownDatabaseField(name="first_seen"),
        "active_days": UnknownDatabaseField(name="active_days"),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_RETENTION_ACTOR_TABLE()

    def to_printed_hogql(self):
        return "retention_actor"
