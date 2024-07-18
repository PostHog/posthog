from collections import defaultdict
from typing import Optional
from django.db import models
import snowflake.connector
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDModel, sane_repr
import uuid
import psycopg2
from posthog.warehouse.types import IncrementalFieldType
from posthog.warehouse.models.ssh_tunnel import SSHTunnel
from posthog.warehouse.util import database_sync_to_async


class ExternalDataSchema(CreatedMetaFields, UUIDModel):
    class Status(models.TextChoices):
        RUNNING = "Running", "Running"
        PAUSED = "Paused", "Paused"
        ERROR = "Error", "Error"
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"

    class SyncType(models.TextChoices):
        FULL_REFRESH = "full_refresh", "full_refresh"
        INCREMENTAL = "incremental", "incremental"

    class SyncFrequency(models.TextChoices):
        DAILY = "day", "Daily"
        WEEKLY = "week", "Weekly"
        MONTHLY = "month", "Monthly"

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
    status: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    last_synced_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    sync_type: models.CharField = models.CharField(max_length=128, choices=SyncType.choices, null=True, blank=True)
    sync_type_config: models.JSONField = models.JSONField(
        default=dict,
        blank=True,
    )
    sync_frequency: models.CharField = models.CharField(
        max_length=128, choices=SyncFrequency.choices, default=SyncFrequency.DAILY, blank=True
    )

    __repr__ = sane_repr("name")

    @property
    def is_incremental(self):
        return self.sync_type == self.SyncType.INCREMENTAL


@database_sync_to_async
def asave_external_data_schema(schema: ExternalDataSchema) -> None:
    schema.save()


def get_schema_if_exists(schema_name: str, team_id: int, source_id: uuid.UUID) -> ExternalDataSchema | None:
    schema = ExternalDataSchema.objects.filter(team_id=team_id, source_id=source_id, name=schema_name).first()
    return schema


@database_sync_to_async
def aget_schema_if_exists(schema_name: str, team_id: int, source_id: uuid.UUID) -> ExternalDataSchema | None:
    return get_schema_if_exists(schema_name=schema_name, team_id=team_id, source_id=source_id)


@database_sync_to_async
def aget_schema_by_id(schema_id: str, team_id: int) -> ExternalDataSchema | None:
    return ExternalDataSchema.objects.prefetch_related("source").get(id=schema_id, team_id=team_id)


@database_sync_to_async
def get_active_schemas_for_source_id(source_id: uuid.UUID, team_id: int):
    return list(ExternalDataSchema.objects.filter(team_id=team_id, source_id=source_id, should_sync=True).all())


def get_all_schemas_for_source_id(source_id: uuid.UUID, team_id: int):
    return list(ExternalDataSchema.objects.filter(team_id=team_id, source_id=source_id).all())


def sync_old_schemas_with_new_schemas(new_schemas: list, source_id: uuid.UUID, team_id: int):
    old_schemas = get_all_schemas_for_source_id(source_id=source_id, team_id=team_id)
    old_schemas_names = [schema.name for schema in old_schemas]

    schemas_to_create = [schema for schema in new_schemas if schema not in old_schemas_names]

    for schema in schemas_to_create:
        ExternalDataSchema.objects.create(name=schema, team_id=team_id, source_id=source_id, should_sync=False)


def filter_snowflake_incremental_fields(columns: list[tuple[str, str]]) -> list[tuple[str, IncrementalFieldType]]:
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, type in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date))
        elif type == "datetime":
            results.append((column_name, IncrementalFieldType.DateTime))
        elif type == "numeric":
            results.append((column_name, IncrementalFieldType.Numeric))

    return results


def get_snowflake_schemas(
    account_id: str, database: str, warehouse: str, user: str, password: str, schema: str, role: Optional[str] = None
) -> dict[str, list[tuple[str, str]]]:
    with snowflake.connector.connect(
        user=user,
        password=password,
        account=account_id,
        warehouse=warehouse,
        database=database,
        schema="information_schema",
        role=role,
    ) as connection:
        with connection.cursor() as cursor:
            if cursor is None:
                raise Exception("Can't create cursor to Snowflake")

            cursor.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = %(schema)s ORDER BY table_name ASC",
                {"schema": schema},
            )
            result = cursor.fetchall()

            schema_list = defaultdict(list)
            for row in result:
                schema_list[row[0]].append((row[1], row[2]))

            return schema_list


def filter_postgres_incremental_fields(columns: list[tuple[str, str]]) -> list[tuple[str, IncrementalFieldType]]:
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, type in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date))
        elif type == "integer" or type == "smallint" or type == "bigint":
            results.append((column_name, IncrementalFieldType.Integer))

    return results


def get_postgres_schemas(
    host: str, port: str, database: str, user: str, password: str, schema: str, ssh_tunnel: SSHTunnel
) -> dict[str, list[tuple[str, str]]]:
    def get_schemas(postgres_host: str, postgres_port: int):
        connection = psycopg2.connect(
            host=postgres_host,
            port=postgres_port,
            dbname=database,
            user=user,
            password=password,
            sslmode="prefer",
            connect_timeout=5,
            sslrootcert="/tmp/no.txt",
            sslcert="/tmp/no.txt",
            sslkey="/tmp/no.txt",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = %(schema)s ORDER BY table_name ASC",
                {"schema": schema},
            )
            result = cursor.fetchall()

            schema_list = defaultdict(list)
            for row in result:
                schema_list[row[0]].append((row[1], row[2]))

        connection.close()

        return schema_list

    if ssh_tunnel.enabled:
        with ssh_tunnel.get_tunnel(host, int(port)) as tunnel:
            if tunnel is None:
                raise Exception("Can't open tunnel to SSH server")

            return get_schemas(tunnel.local_bind_host, tunnel.local_bind_port)

    return get_schemas(host, int(port))
