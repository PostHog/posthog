import dagster
from dagster_docker import PipesDockerClient
from django.conf import settings

from dags.common import JobOwners
from dags.snapshot_project_data import snapshot_project_data
from posthog.models.utils import uuid7


class CompileEvalsDbConfig(dagster.Config):
    project_ids: list[int]


@dagster.asset(
    check_specs=[dagster.AssetCheckSpec(name="no_empty_dump", asset="compile_evals_db")],
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
)
def compile_evals_db(
    context: dagster.AssetExecutionContext, config: CompileEvalsDbConfig, docker_pipes_client: PipesDockerClient
):
    """
    Spawns a posthog-ai-evals:test container in privileged mode, runs database migrations,
    and returns the path to the exported database dump tar file.
    """
    if settings.DEBUG:
        bucket_name = settings.OBJECT_STORAGE_BUCKET
        endpoint_url = "http://objectstorage.posthog.orb.local"
    else:
        bucket_name = settings.OBJECT_STORAGE_BUCKET
        endpoint_url = "https://s3.amazonaws.com"
        raise NotImplementedError("Not implemented for production")

    return docker_pipes_client.run(
        context=context,
        image="posthog-ai-evals:test",
        container_kwargs={
            "privileged": True,
            "auto_remove": True,
        },
        env={
            "EVAL_SCRIPT": "python bin/evals/export_modeled_db.py",
            "OBJECT_STORAGE_ACCESS_KEY_ID": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "OBJECT_STORAGE_SECRET_ACCESS_KEY": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "PROJECT_IDS": ",".join(map(str, config.project_ids)),
        },
        extras={
            "bucket_name": bucket_name,
            "endpoint_url": endpoint_url,
            "file_key": f"{settings.OBJECT_STORAGE_MAX_AI_EVALS_FOLDER}/postgres/db_{uuid7()}.tar",
            "database_url": "postgres://posthog:posthog@db:5432/posthog",
        },
    ).get_materialize_result()


class ExportProjectsConfig(dagster.Config):
    project_ids: list[int]
    """Project IDs to run the evaluation for."""


class EvaluationConfig(dagster.Config):
    evaluation_module: str
    """Python module containing the evaluation runner."""


@dagster.op(out=dagster.DynamicOut(int))
def export_projects(config: ExportProjectsConfig):
    for pid in config.project_ids:
        yield dagster.DynamicOutput(pid, mapping_key=str(pid))


@dagster.job(
    description="Runs an AI evaluation",
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
    config=dagster.RunConfig(ops={"export_projects": ExportProjectsConfig(project_ids=[])}),
)
def run_evaluation():
    project_ids = export_projects()
    project_ids.map(snapshot_project_data)
