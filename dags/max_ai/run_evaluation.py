import dagster
from django.conf import settings

from dags.common import JobOwners
from dags.max_ai.snapshot_project_data import (
    snapshot_clickhouse_project_data,
    snapshot_postgres_project_data,
)


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
    experiment_name: str
    """Name of the experiment."""
    evaluation_module: str
    """Python module containing the evaluation runner."""


@dagster.job(
    description="Runs an AI evaluation",
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
    config=dagster.RunConfig(
        ops={
            "export_projects": ExportProjectsConfig(project_ids=[]),
        }
    ),
)
def run_evaluation():
    project_ids = export_projects()
    project_ids.map(snapshot_postgres_project_data)
    project_ids.map(snapshot_clickhouse_project_data)
