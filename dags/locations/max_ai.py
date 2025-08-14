import dagster

from dags.max_ai.snapshot_project_data import snapshot_project_data

from . import resources

defs = dagster.Definitions(
    jobs=[snapshot_project_data],
    resources=resources,
)
