from typing import TypeVar

import dagster
from dagster_aws.s3.resources import S3Resource

from dags.common import JobOwners
from dags.max_ai.utils import check_dump_exists, compose_postgres_dump_path, dump_model
from ee.hogai.eval.schema import (
    BaseSnapshot,
    DataWarehouseTableSnapshot,
    GroupTypeMappingSnapshot,
    PostgresProjectDataSnapshot,
    PropertyDefinitionSnapshot,
    TeamSnapshot,
)

DEFAULT_RETRY_POLICY = dagster.RetryPolicy(
    max_retries=4,
    delay=2,  # 2 seconds
    backoff=dagster.Backoff.EXPONENTIAL,
    jitter=dagster.Jitter.PLUS_MINUS,
)


SchemaBound = TypeVar("SchemaBound", bound=BaseSnapshot)


def snapshot_postgres_model(
    context: dagster.OpExecutionContext,
    model_type: type[SchemaBound],
    file_name: str,
    s3: S3Resource,
    project_id: int,
    code_version: str | None = None,
) -> str:
    file_key = compose_postgres_dump_path(project_id, file_name, code_version)
    if check_dump_exists(s3, file_key):
        context.log.info(f"Skipping {file_key} because it already exists")
        return file_key
    context.log.info(f"Dumping {file_key}")
    with dump_model(s3=s3, schema=model_type, file_key=file_key) as dump:
        dump(model_type.serialize_for_project(project_id))
    return file_key


@dagster.op(
    description="Snapshots Postgres project data (property definitions, DWH schema, etc.)",
    retry_policy=DEFAULT_RETRY_POLICY,
    code_version="v1",
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
)
def snapshot_postgres_project_data(
    context: dagster.OpExecutionContext, project_id: int, s3: S3Resource
) -> PostgresProjectDataSnapshot:
    context.log.info(f"Snapshotting Postgres project data for {project_id}")
    snapshot_map: dict[str, type[BaseSnapshot]] = {
        "project": TeamSnapshot,
        "property_definitions": PropertyDefinitionSnapshot,
        "group_type_mappings": GroupTypeMappingSnapshot,
        "data_warehouse_tables": DataWarehouseTableSnapshot,
    }
    deps = {
        file_name: snapshot_postgres_model(context, model_type, file_name, s3, project_id, context.op_def.version)
        for file_name, model_type in snapshot_map.items()
    }
    context.log_event(
        dagster.AssetMaterialization(
            asset_key="project_postgres_snapshot",
            description="Avro snapshots of project Postgres data",
            metadata={"project_id": project_id, **deps},
            tags={"owner": JobOwners.TEAM_MAX_AI.value},
        )
    )
    return PostgresProjectDataSnapshot(**deps)


@dagster.job(
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
)
def snapshot_project_data():
    # Temporary job for testing
    snapshot_postgres_project_data()
