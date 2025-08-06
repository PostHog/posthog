import dagster
from dagster_docker import PipesDockerClient
from django.conf import settings

from dags.common import JobOwners
from dags.max_ai.snapshot_project_data import (
    ClickhouseProjectDataSnapshot,
    PostgresProjectDataSnapshot,
    snapshot_clickhouse_project_data,
    snapshot_postgres_project_data,
)
from ee.hogai.eval.schema import Snapshot


def get_object_storage_endpoint() -> dagster.EnvVar | str:
    if settings.DEBUG:
        return dagster.EnvVar("EVALS_DIND_OBJECT_STORAGE_ENDPOINT")
    return settings.OBJECT_STORAGE_ENDPOINT


class ExportProjectsConfig(dagster.Config):
    project_ids: list[int]
    """Project IDs to run the evaluation for."""


@dagster.op(out=dagster.DynamicOut(int))
def export_projects(config: ExportProjectsConfig):
    seen_projects = set()
    for pid in config.project_ids:
        if pid in seen_projects:
            continue
        seen_projects.add(pid)
        yield dagster.DynamicOutput(pid, mapping_key=str(pid))


class EvaluationConfig(dagster.Config):
    evaluation_module: str
    """Python module containing the evaluation runner."""


@dagster.op
def spawn_evaluation_container(
    context: dagster.OpExecutionContext,
    config: EvaluationConfig,
    docker_pipes_client: PipesDockerClient,
    project_ids: list[int],
    postgres_snapshots: list[PostgresProjectDataSnapshot],
    clickhouse_snapshots: list[ClickhouseProjectDataSnapshot],
):
    return docker_pipes_client.run(
        context=context,
        image="posthog-ai-evals:test",
        container_kwargs={
            "privileged": True,
            "auto_remove": True,
        },
        env={
            "EVAL_SCRIPT": f"pytest {config.evaluation_module}",
            "OBJECT_STORAGE_ACCESS_KEY_ID": settings.OBJECT_STORAGE_ACCESS_KEY_ID,  # type: ignore
            "OBJECT_STORAGE_SECRET_ACCESS_KEY": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,  # type: ignore
        },
        extras={
            "endpoint_url": get_object_storage_endpoint(),
            "bucket_name": settings.OBJECT_STORAGE_BUCKET,
            "project_snapshots": [
                Snapshot(project=project_id, postgres=postgres, clickhouse=clickhouse).model_dump()
                for project_id, postgres, clickhouse in zip(project_ids, postgres_snapshots, clickhouse_snapshots)
            ],
        },
    ).get_materialize_result()


@dagster.job(
    description="Runs an AI evaluation",
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
    config=dagster.RunConfig(
        ops={
            "export_projects": ExportProjectsConfig(project_ids=[]),
            "spawn_evaluation_container": EvaluationConfig(evaluation_module=""),
        }
    ),
)
def run_evaluation():
    project_ids = export_projects()
    postgres_snapshots = project_ids.map(snapshot_postgres_project_data)
    clickhouse_snapshots = project_ids.map(snapshot_clickhouse_project_data)
    spawn_evaluation_container(project_ids.collect(), postgres_snapshots.collect(), clickhouse_snapshots.collect())
    # return evaluation_result
