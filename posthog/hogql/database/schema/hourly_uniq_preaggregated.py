from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    DatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

from posthog.clickhouse.preaggregation.hourly_uniq_sql import TABLE


class HourlyUniqPreaggregatedTable(Table):
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order")
    )
    fields: dict = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(name="job_id"),
        "time_window_start": DateTimeDatabaseField(name="time_window_start"),
        "metric_index": IntegerDatabaseField(name="metric_index"),
        "uniq_state": DatabaseField(name="uniq_state"),
    }

    def to_printed_clickhouse(self, context):
        return TABLE

    def to_printed_hogql(self):
        return TABLE
