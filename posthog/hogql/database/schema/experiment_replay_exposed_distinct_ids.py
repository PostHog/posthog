from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

from posthog.clickhouse.preaggregation.experiment_replay_exposed_distinct_ids_sql import (
    DISTRIBUTED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE,
)


class ExperimentReplayExposedDistinctIdsTable(Table):
    description: str = (
        "Internal cache of an experiment's exposed population expanded to distinct ids, one row per distinct id "
        "per computed generation, carrying the owning person's first exposure time."
    )
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order")
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "cache_key": StringDatabaseField(
            name="cache_key",
            description="Opaque key naming one computed generation of one experiment's exposed population.",
        ),
        "distinct_id": StringDatabaseField(
            name="distinct_id",
            description="A distinct id belonging to an exposed person; join to recordings' distinct_id.",
        ),
        "first_exposure_time": DateTimeDatabaseField(
            name="first_exposure_time",
            description="Timestamp of the owning person's first exposure to the experiment (UTC).",
        ),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE()

    def to_printed_hogql(self):
        return "experiment_replay_exposed_distinct_ids"
