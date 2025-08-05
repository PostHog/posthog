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
from posthog.models.utils import uuid7


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
    context: dagster.AssetExecutionContext,
    config: EvaluationConfig,
    docker_pipes_client: PipesDockerClient,
    postgres_snapshots: PostgresProjectDataSnapshot,
    clickhouse_snapshots: ClickhouseProjectDataSnapshot,
):
    return docker_pipes_client.run(
        context=context,
        image="posthog-ai-evals:test",
        container_kwargs={
            "privileged": True,
            "auto_remove": True,
        },
        env={
            "EVAL_SCRIPT": "python bin/evals/run_evaluation.py",
            "EVAL_MODULE": config.evaluation_module,
            "OBJECT_STORAGE_ACCESS_KEY_ID": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "OBJECT_STORAGE_SECRET_ACCESS_KEY": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "PROJECT_IDS": ",".join(map(str, config.project_ids)),
        },
        extras={
            "endpoint_url": get_object_storage_endpoint(),
            "bucket_name": settings.OBJECT_STORAGE_BUCKET,
            "file_key": f"{settings.OBJECT_STORAGE_MAX_AI_EVALS_FOLDER}/postgres/db_{uuid7()}.tar",
            "database_url": "postgres://posthog:posthog@db:5432/posthog",
            "postgres_snapshots": postgres_snapshots.model_dump(),
            "clickhouse_snapshots": clickhouse_snapshots.model_dump(),
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
    evaluation_result = spawn_evaluation_container(postgres_snapshots, clickhouse_snapshots)
    return evaluation_result
