import dagster

from dags.common import JobOwners
from dags.max_ai.snapshot_project_data import snapshot_clickhouse_project_data, snapshot_postgres_project_data


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


@dagster.job(
    description="Runs an AI evaluation",
    tags={
        "owner": JobOwners.TEAM_MAX_AI.value,
        "dagster/max_runtime": 60 * 60,  # 1 hour
    },
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 4}),
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
