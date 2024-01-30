from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDModel, sane_repr
import uuid
import psycopg
from django.conf import settings
from posthog.warehouse.util import database_sync_to_async


class ExternalDataSchema(CreatedMetaFields, UUIDModel):
    name: models.CharField = models.CharField(max_length=400)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    source: models.ForeignKey = models.ForeignKey(
        "posthog.ExternalDataSource", related_name="schemas", on_delete=models.CASCADE
    )
    table: models.ForeignKey = models.ForeignKey(
        "posthog.DataWarehouseTable", on_delete=models.SET_NULL, null=True, blank=True
    )
    should_sync: models.BooleanField = models.BooleanField(default=True)
    latest_error: models.TextField = models.TextField(
        null=True, help_text="The latest error that occurred when syncing this schema."
    )
    last_synced_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)

    __repr__ = sane_repr("name")


def get_schema_if_exists(schema_name: str, team_id: int, source_id: uuid.UUID) -> ExternalDataSchema | None:
    schema = ExternalDataSchema.objects.filter(team_id=team_id, source_id=source_id, name=schema_name).first()
    return schema


@database_sync_to_async
def aget_schema_if_exists(schema_name: str, team_id: int, source_id: uuid.UUID) -> ExternalDataSchema | None:
    return get_schema_if_exists(schema_name=schema_name, team_id=team_id, source_id=source_id)


def get_active_schemas_for_source_id(source_id: uuid.UUID, team_id: int):
    schemas = ExternalDataSchema.objects.filter(team_id=team_id, source_id=source_id, should_sync=True).values().all()
    return [val["name"] for val in schemas]


def get_all_schemas_for_source_id(source_id: uuid.UUID, team_id: int):
    schemas = ExternalDataSchema.objects.filter(team_id=team_id, source_id=source_id).values().all()
    return [val["name"] for val in schemas]


def sync_old_schemas_with_new_schemas(new_schemas: list, source_id: uuid.UUID, team_id: int):
    old_schemas = get_all_schemas_for_source_id(source_id=source_id, team_id=team_id)
    schemas_to_create = [schema for schema in new_schemas if schema not in old_schemas]

    for schema in schemas_to_create:
        ExternalDataSchema.objects.create(name=schema, team_id=team_id, source_id=source_id, should_sync=False)


def get_postgres_schemas(host: str, port: str, database: str, user: str, password: str, schema: str):
    connection = psycopg.Connection.connect(
        host=host,
        port=int(port),
        dbname=database,
        user=user,
        password=password,
        sslmode="prefer" if settings.TEST or settings.DEBUG else "require",
    )

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %(schema)s", {"schema": schema}
        )
        result = cursor.fetchall()
        result = [row[0] for row in result]

    connection.close()

    return result
