import dagster
from dagster_docker import PipesDockerClient

from dags.compile_evals_db import compile_evals_db, run_evaluation

from . import resources

defs = dagster.Definitions(
    assets=[compile_evals_db],
    jobs=[run_evaluation],
    resources={
        **resources,
        "docker_pipes_client": PipesDockerClient(),
    },
)
