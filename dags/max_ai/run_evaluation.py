import os

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
from ee.hogai.eval.schema import DatasetInput, EvalsDockerImageConfig, ProjectSnapshot


def get_object_storage_endpoint() -> str:
    if settings.DEBUG:
        val = dagster.EnvVar("EVALS_DIND_OBJECT_STORAGE_ENDPOINT").get_value()
        if not val:
            raise ValueError("EVALS_DIND_OBJECT_STORAGE_ENDPOINT is not set")
        return val
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
    image: str
    """Name of the Docker image to run."""
    image_tag: str
    """Tag of the Docker image to run."""
    experiment_name: str
    """Name of the experiment."""
    evaluation_module: str
    """Python module containing the evaluation runner."""


def get_registry_credentials():
    return {
        "url": dagster.EnvVar("AWS_EKS_REGISTRY_URL").get_value(),
        "username": "AWS",
        "password": dagster.EnvVar("AWS_EKS_REGISTRY_PASSWORD").get_value(),
    }


@dagster.op
def spawn_evaluation_container(
    context: dagster.OpExecutionContext,
    config: EvaluationConfig,
    docker_pipes_client: PipesDockerClient,
    project_ids: list[int],
    postgres_snapshots: list[PostgresProjectDataSnapshot],
    clickhouse_snapshots: list[ClickhouseProjectDataSnapshot],
):
    evaluation_config = EvalsDockerImageConfig(
        aws_endpoint_url=get_object_storage_endpoint(),
        aws_bucket_name=settings.OBJECT_STORAGE_BUCKET,
        project_snapshots=[
            ProjectSnapshot(project=project_id, postgres=postgres, clickhouse=clickhouse).model_dump()
            for project_id, postgres, clickhouse in zip(project_ids, postgres_snapshots, clickhouse_snapshots)
        ],
        experiment_name=config.experiment_name,
        dataset=[
            DatasetInput(
                project_id=project_id,
                input={"query": "List all events from the last 7 days. Use SQL."},
                expected={"output": "SELECT * FROM events WHERE timestamp >= now() - INTERVAL 7 day"},
            )
            for project_id in project_ids
        ],
    )

    asset_result = docker_pipes_client.run(
        context=context,
        image=f"{config.image}:{config.image_tag}",
        container_kwargs={
            "privileged": True,
            "auto_remove": True,
        },
        env={
            "EVAL_SCRIPT": f"pytest {config.evaluation_module} -s -vv",
            "OBJECT_STORAGE_ACCESS_KEY_ID": settings.OBJECT_STORAGE_ACCESS_KEY_ID,  # type: ignore
            "OBJECT_STORAGE_SECRET_ACCESS_KEY": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,  # type: ignore
            "OPENAI_API_KEY": settings.OPENAI_API_KEY,
            "ANTHROPIC_API_KEY": settings.ANTHROPIC_API_KEY,
            "GEMINI_API_KEY": settings.GEMINI_API_KEY,
            "INKEEP_API_KEY": settings.INKEEP_API_KEY,
            "PPLX_API_KEY": settings.PPLX_API_KEY,
            "AZURE_INFERENCE_ENDPOINT": settings.AZURE_INFERENCE_ENDPOINT,
            "AZURE_INFERENCE_CREDENTIAL": settings.AZURE_INFERENCE_CREDENTIAL,
            "BRAINTRUST_API_KEY": settings.BRAINTRUST_API_KEY,
        },
        extras=evaluation_config.model_dump(exclude_unset=True),
        registry=get_registry_credentials(),
    ).get_materialize_result()

    context.log_event(
        dagster.AssetMaterialization(
            asset_key=asset_result.asset_key or "evaluation_report",
            metadata=asset_result.metadata,
            tags={"owner": JobOwners.TEAM_MAX_AI.value},
        )
    )


@dagster.job(
    description="Runs an AI evaluation",
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
    config=dagster.RunConfig(
        ops={
            "export_projects": ExportProjectsConfig(project_ids=[]),
            "spawn_evaluation_container": EvaluationConfig(
                evaluation_module="",
                experiment_name="offline_evaluation",
                image=f"{os.getenv('AWS_EKS_REGISTRY_URL')}/{os.getenv('AWS_EKS_REPOSITORY_NAME')}",
                image_tag="master",
            ),
        }
    ),
)
def run_evaluation():
    project_ids = export_projects()
    postgres_snapshots = project_ids.map(snapshot_postgres_project_data)
    clickhouse_snapshots = project_ids.map(snapshot_clickhouse_project_data)
    spawn_evaluation_container(project_ids.collect(), postgres_snapshots.collect(), clickhouse_snapshots.collect())
