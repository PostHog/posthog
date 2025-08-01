import dagster
from dagster_docker import PipesDockerClient

from dags.database_migration import migrate_and_export_database_dump

from . import resources

defs = dagster.Definitions(
    assets=[migrate_and_export_database_dump],
    resources={
        **resources,
        "docker_pipes_client": PipesDockerClient(),
    },
)
