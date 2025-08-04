import dagster
from dagster_docker import PipesDockerClient

from dags.database_migration import migrate_and_export_database_dump
from dags.snapshot_project_data import (
    snapshot_project_data,
    snapshot_property_definitions,
)

from . import resources

defs = dagster.Definitions(
    assets=[migrate_and_export_database_dump, snapshot_property_definitions],
    jobs=[snapshot_project_data],
    resources={
        **resources,
        "docker_pipes_client": PipesDockerClient(),
    },
)
