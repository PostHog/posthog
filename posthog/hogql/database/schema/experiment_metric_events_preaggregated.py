from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

from posthog.clickhouse.preaggregation.experiment_metric_events_sql import DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE


class ExperimentMetricEventsPreaggregatedTable(Table):
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order")
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(name="job_id"),
        "entity_id": StringDatabaseField(name="entity_id"),
        "timestamp": DateTimeDatabaseField(name="timestamp"),
        "event_uuid": StringDatabaseField(name="event_uuid"),
        "session_id": StringDatabaseField(name="session_id"),
        "numeric_value": FloatDatabaseField(name="numeric_value"),
        # steps is Array(UInt8) in ClickHouse but HogQL doesn't have a typed array field;
        # queries will use arrayElement() to access individual step indicators
        "steps": StringDatabaseField(name="steps"),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE()

    def to_printed_hogql(self):
        return "experiment_metric_events_preaggregated"
