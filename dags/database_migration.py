import dagster
from dagster_docker import PipesDockerClient
from django.conf import settings

from dags.common import JobOwners
from posthog.models.utils import uuid7


@dagster.asset(
    group_name="database_migration",
    description="Runs database migrations in posthog-ai-evals:test container and produces a compressed tar database dump",
    tags={"owner": JobOwners.TEAM_MAX_AI.value, "type": "database_migration"},
)
def migrate_and_export_database_dump(context: dagster.AssetExecutionContext, docker_pipes_client: PipesDockerClient):
    """
    Spawns a posthog-ai-evals:test container in privileged mode, runs database migrations,
    and returns the path to the exported database dump tar file.
    """
    prefix = "psql"
    if settings.DEBUG:
        s3_path = f"{settings.OBJECT_STORAGE_ENDPOINT}/{settings.OBJECT_STORAGE_MAX_AI_EVALS_FOLDER}/{prefix}"
    else:
        s3_path = f"https://{settings.OBJECT_STORAGE_MAX_AI_EVALS_FOLDER}.s3.amazonaws.com/{prefix}"
        raise NotImplementedError("Not implemented for production")

    return docker_pipes_client.run(
        context=context,
        image="posthog-ai-evals:test",
        container_kwargs={
            "privileged": True,
        },
        env={
            "EVALS_SCRIPT": "python bin/evals/export_modeled_db.py",
        },
        extras={
            "s3_path": s3_path,
            "file_key": f"db_{uuid7()}.tar",
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
