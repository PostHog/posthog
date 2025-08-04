import dagster
from dagster_docker import PipesDockerClient

from dags.compile_evals_db import compile_evals_db
from dags.snapshot_project_data import (
    snapshot_project_data,
    snapshot_property_definitions,
)

from . import resources

defs = dagster.Definitions(
    assets=[compile_evals_db, snapshot_property_definitions],
    jobs=[snapshot_project_data],
    resources={
        **resources,
        "docker_pipes_client": PipesDockerClient(),
    },
)
