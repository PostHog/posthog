import dagster
from dagster_docker import PipesDockerClient

from dags.max_ai.run_evaluation import run_evaluation

from . import resources

defs = dagster.Definitions(
    jobs=[run_evaluation],
    resources={
        **resources,
        "docker_pipes_client": PipesDockerClient(),
    },
)
