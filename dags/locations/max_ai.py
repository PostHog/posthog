import dagster

from dags import (
    snapshot_team_data,
)

from . import resources

defs = dagster.Definitions(
    jobs=[
        snapshot_team_data.snapshot_team_data_job,
    ],
    resources=resources,
)
