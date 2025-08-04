from tempfile import TemporaryFile

import dagster
from dagster_aws.s3 import S3Resource
from django.conf import settings
from fastavro import parse_schema, writer
from pydantic_avro import AvroBase

from dags.common import JobOwners
from posthog.models import DataWarehouseTable, PropertyDefinition


class SnapshotConfig(dagster.Config):
    project_id: int


# posthog/models/property_definition.py
class PropertyDefinitionSchema(AvroBase):
    name: str
    is_numerical: bool
    property_type: str | None
    type: int
    group_type_index: int | None


def compose_dump_path(project_id: int, file_name: str) -> str:
    return f"{settings.OBJECT_STORAGE_MAX_AI_EVALS_FOLDER}/models/{project_id}/{file_name}"


@dagster.asset(
    description="Snapshots property definitions",
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
)
def snapshot_property_definitions(config: SnapshotConfig, s3: S3Resource):
    with TemporaryFile() as f:
        models_to_dump = []
        for table in DataWarehouseTable.objects.filter(team_id=config.project_id).iterator(500):
            model = DataWarehouseTableSchema(
                name=table.name,
                format=table.format,
                columns=table.columns,
            )
            models_to_dump.append(model.model_dump())
        writer(f, parse_schema(DataWarehouseTableSchema.avro_schema()), models_to_dump)

        file_key = compose_dump_path(config.project_id, "dwh_tables.avro")
        s3.get_client().upload_fileobj(f, settings.OBJECT_STORAGE_BUCKET, file_key)
    return dagster.MaterializeResult(metadata={"key": file_key})


class DataWarehouseTableSchema(AvroBase):
    name: str
    format: str
    columns: list[str]


@dagster.asset(
    description="Snapshots property definitions",
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
)
def snapshot_data_warehouse_tables(config: SnapshotConfig, s3: S3Resource):
    with TemporaryFile() as f:
        models_to_dump = []
        for prop in PropertyDefinition.objects.filter(project_id=config.project_id).iterator(500):
            model = PropertyDefinitionSchema(
                name=prop.name,
                is_numerical=prop.is_numerical,
                property_type=prop.property_type,
                type=prop.type,
                group_type_index=prop.group_type_index,
            )
            models_to_dump.append(model.model_dump())
        writer(f, parse_schema(PropertyDefinitionSchema.avro_schema()), models_to_dump)

        file_key = compose_dump_path(config.project_id, "prop_defs.avro")
        s3.get_client().upload_fileobj(f, settings.OBJECT_STORAGE_BUCKET, file_key)
    return dagster.MaterializeResult(metadata={"key": file_key})


snapshot_project_data = dagster.define_asset_job(
    name="snapshot_project_data",
    description="Snapshots project data (property definitions, DWH schema, etc.)",
    selection=[snapshot_property_definitions.key, snapshot_data_warehouse_tables.key],
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
    config=dagster.RunConfig(
        ops={
            "snapshot_property_definitions": SnapshotConfig(project_id=0),
            "snapshot_data_warehouse_tables": SnapshotConfig(project_id=0),
        }
    ),
)
