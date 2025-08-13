from collections.abc import Sequence
from contextlib import contextmanager
from tempfile import TemporaryFile

import dagster
from dagster_aws.s3 import S3Resource
from django.conf import settings
from fastavro import parse_schema, writer
from pydantic_avro import AvroBase

from dags.common import JobOwners
from dags.max_ai.utils import compose_postgres_dump_path
from ee.hogai.eval.schema import (
    DataWarehouseTableSchema,
    GroupTypeMappingSchema,
    PostgresProjectDataSnapshot,
    PropertyDefinitionSchema,
    TeamSchema,
)

DEFAULT_RETRY_POLICY = dagster.RetryPolicy(
    max_retries=4,
    delay=2,  # 2 seconds
    backoff=dagster.Backoff.EXPONENTIAL,
    jitter=dagster.Jitter.PLUS_MINUS,
)


@contextmanager
def dump_model(*, s3: S3Resource, schema: type[AvroBase], file_key: str):
    with TemporaryFile() as f:
        parsed_schema = parse_schema(schema.avro_schema())

        def dump(models: Sequence[AvroBase]):
            writer(f, parsed_schema, (model.model_dump() for model in models))

        yield dump

        f.seek(0)
        s3.get_client().upload_fileobj(f, settings.OBJECT_STORAGE_BUCKET, file_key)


SnapshotModelOutput = tuple[str, str]


def snapshot_project(s3: S3Resource, project_id: int, code_version: str | None = None) -> SnapshotModelOutput:
    file_key = compose_postgres_dump_path(project_id, "team", code_version)
    with dump_model(s3=s3, schema=TeamSchema, file_key=file_key) as dump:
        dump(TeamSchema.serialize_for_project(project_id))
    return "project", file_key


def snapshot_property_definitions(
    s3: S3Resource, project_id: int, code_version: str | None = None
) -> SnapshotModelOutput:
    file_key = compose_postgres_dump_path(project_id, "prop_defs", code_version)
    with dump_model(s3=s3, schema=PropertyDefinitionSchema, file_key=file_key) as dump:
        dump(PropertyDefinitionSchema.serialize_for_project(project_id))
    return "property_definitions", file_key


def snapshot_group_type_mappings(
    s3: S3Resource, project_id: int, code_version: str | None = None
) -> SnapshotModelOutput:
    file_key = compose_postgres_dump_path(project_id, "group_type_mappings", code_version)
    with dump_model(s3=s3, schema=GroupTypeMappingSchema, file_key=file_key) as dump:
        dump(GroupTypeMappingSchema.serialize_for_project(project_id))
    return "group_type_mappings", file_key


def snapshot_data_warehouse_tables(s3: S3Resource, project_id: int, code_version: str | None = None):
    file_key = compose_postgres_dump_path(project_id, "dwh_tables", code_version)
    with dump_model(s3=s3, schema=DataWarehouseTableSchema, file_key=file_key) as dump:
        dump(DataWarehouseTableSchema.serialize_for_project(project_id))
    return "data_warehouse_tables", file_key


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
    deps = dict(
        (
            snapshot_project(s3, project_id, context.op_def.version),
            snapshot_property_definitions(s3, project_id, context.op_def.version),
            snapshot_group_type_mappings(s3, project_id, context.op_def.version),
            snapshot_data_warehouse_tables(s3, project_id, context.op_def.version),
        )
    )
    context.log_event(
        dagster.AssetMaterialization(
            asset_key="project_postgres_snapshots",
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
