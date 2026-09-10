from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    Table,
)

from posthog.clickhouse.preaggregation.experiment_exposures_sql import DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE


class ExperimentExposuresPreaggregatedTable(Table):
    description: str = (
        "Internal preaggregated table of experiment exposures, one row per entity per experiment job recording the "
        "variant the entity was exposed to and the exposure time window."
    )
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order")
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(
            name="job_id", description="Identifier of the preaggregation job that produced this row."
        ),
        "entity_id": StringDatabaseField(
            name="entity_id", description="Identifier of the exposed entity (person or group) being analyzed."
        ),
        "variant": StringDatabaseField(
            name="variant", description="Experiment variant the entity was exposed to (e.g. 'control', 'test')."
        ),
        "first_exposure_time": DateTimeDatabaseField(
            name="first_exposure_time", description="Timestamp of the entity's first exposure to the experiment (UTC)."
        ),
        "last_exposure_time": DateTimeDatabaseField(
            name="last_exposure_time",
            description="Timestamp of the entity's most recent exposure to the experiment (UTC).",
        ),
        "exposure_event_uuid": StringDatabaseField(
            name="exposure_event_uuid",
            description="UUID of the event that recorded the first exposure; join to `events.uuid`.",
        ),
        "exposure_session_id": StringDatabaseField(
            name="exposure_session_id", description="Session in which the first exposure occurred; join to `sessions`."
        ),
        "breakdown_value": StringArrayDatabaseField(
            name="breakdown_value", description="Breakdown dimension values associated with this exposure."
        ),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE()

    def to_printed_hogql(self):
        return "experiment_exposures_preaggregated"
