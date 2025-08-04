from tempfile import TemporaryFile

import dagster
from dagster_aws.s3 import S3Resource
from dagster_docker import PipesDockerClient
from django.conf import settings
from fastavro import parse_schema, writer
from pydantic_avro import AvroBase

from dags.common import JobOwners
from posthog.models import PropertyDefinition
from posthog.models.utils import uuid7


class SnapshotConfig(dagster.Config):
    project_id: int


# posthog/models/property_definition.py
class PropertyDefinitionSchema(AvroBase):
    name: str
    is_numerical: bool
    property_type: str | None
    type: int
    group_type_index: int | None


@dagster.asset(
    name="snapshot_property_definitions",
    description="Snapshots property definitions",
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
)
def snapshot_property_definitions(config: SnapshotConfig, s3: S3Resource):
    with TemporaryFile() as f:
        for prop in PropertyDefinition.objects.filter(project_id=config.project_id).iterator(500):
            model = PropertyDefinitionSchema(
                name=prop.name,
                is_numerical=prop.is_numerical,
                property_type=prop.property_type,
                type=prop.type,
                group_type_index=prop.group_type_index,
            )
            writer(f, parse_schema(PropertyDefinitionSchema.avro_schema()), model.model_dump())
        file_key = f"models/{config.project_id}/prop_defs.avro"
        s3.get_client().upload_fileobj(f, settings.OBJECT_STORAGE_MAX_AI_EVALS_FOLDER, file_key)
    return {
        "bucket": settings.OBJECT_STORAGE_MAX_AI_EVALS_FOLDER,
        "key": file_key,
    }


@dagster.asset(
    name="snapshot_project_data",
    description="Snapshots project data (property definitions, DWH schema, etc.)",
    deps=[snapshot_property_definitions],
    tags={"owner": JobOwners.TEAM_MAX_AI.value},
)
def snapshot_project_data(config: SnapshotConfig):
    pass


@dagster.asset(
    group_name="database_migration",
    description="Runs database migrations in posthog-ai-evals:test container and produces a compressed tar database dump",
    check_specs=[dagster.AssetCheckSpec(name="no_empty_dump", asset="migrate_and_export_database_dump")],
    tags={"owner": JobOwners.TEAM_MAX_AI.value, "type": "database_migration"},
)
def migrate_and_export_database_dump(context: dagster.AssetExecutionContext, docker_pipes_client: PipesDockerClient):
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
        },
        extras={
            "bucket_name": bucket_name,
            "endpoint_url": endpoint_url,
            "file_key": f"{settings.OBJECT_STORAGE_MAX_AI_EVALS_FOLDER}/postgres/db_{uuid7()}.tar",
            "database_url": "postgres://posthog:posthog@db:5432/posthog",
        },
    ).get_materialize_result()


@dagster.job(
    name="migrate_db_job",
    description="Complete database migration workflow: spawn container, run migrations, export dump",
    tags={"owner": JobOwners.TEAM_MAX_AI.value, "type": "database_migration"},
)
def migrate_db_job():
    """
    Job that orchestrates the complete database migration workflow:
    1. Spawns posthog-ai-evals:test container in privileged mode
    2. Executes 'bin/check_postgres_up && python manage.py migrate'
    3. Exports the migrated database dump
    4. Validates the exported dump
    """
    migrate_and_export_database_dump()
