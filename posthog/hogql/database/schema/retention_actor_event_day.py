from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    DateDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

from posthog.clickhouse.preaggregation.retention_actor_event_day_sql import DISTRIBUTED_RETENTION_ACTOR_EVENT_DAY_TABLE


class RetentionActorEventDayTable(Table):
    # Same hints as `WebStatsPreaggregatedTable`: `load_balancing="in_order"` so reads
    # land on the same replica that wrote the precompute (read-your-writes), and
    # `optimize_skip_unused_shards=1` to prune shards using the `job_id IN (...)` filter
    # (sharded by sipHash64(team_id, actor_id) — the prune is less aggressive than web
    # analytics' but still wins on multi-team reads).
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order", optimize_skip_unused_shards=True)
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(name="job_id"),
        "day": DateDatabaseField(name="day"),
        "actor_id": StringDatabaseField(name="actor_id"),
        "group_type_index": IntegerDatabaseField(name="group_type_index"),
        "event": StringDatabaseField(name="event"),
        "first_ts": DateTimeDatabaseField(name="first_ts"),
        "computed_at": DateTimeDatabaseField(name="computed_at"),
        "expires_at": DateTimeDatabaseField(name="expires_at"),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_RETENTION_ACTOR_EVENT_DAY_TABLE()

    def to_printed_hogql(self):
        return "retention_actor_event_day"
