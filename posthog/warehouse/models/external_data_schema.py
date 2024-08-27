from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional
from django.db import models
from django_deprecate_fields import deprecate_field
import snowflake.connector
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UUIDModel, UpdatedMetaFields, sane_repr
import uuid
import psycopg2
import pymysql
from .external_data_source import ExternalDataSource
from posthog.warehouse.data_load.service import (
    external_data_workflow_exists,
    pause_external_data_schedule,
    sync_external_data_job_workflow,
    unpause_external_data_schedule,
)
from posthog.warehouse.types import IncrementalFieldType
from posthog.warehouse.models.ssh_tunnel import SSHTunnel
from posthog.warehouse.util import database_sync_to_async


class ExternalDataSchema(CreatedMetaFields, UpdatedMetaFields, UUIDModel, DeletedMetaFields):
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

    name = models.CharField(max_length=400)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    source = models.ForeignKey("posthog.ExternalDataSource", related_name="schemas", on_delete=models.CASCADE)
    table = models.ForeignKey("posthog.DataWarehouseTable", on_delete=models.SET_NULL, null=True, blank=True)
    should_sync = models.BooleanField(default=True)
    latest_error = models.TextField(null=True, help_text="The latest error that occurred when syncing this schema.")
    status = models.CharField(max_length=400, null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_type = models.CharField(max_length=128, choices=SyncType.choices, null=True, blank=True)
    sync_type_config = models.JSONField(
        default=dict,
        blank=True,
    )
    # Deprecated in favour of `sync_frequency_interval`
    sync_frequency = deprecate_field(
        models.CharField(max_length=128, choices=SyncFrequency.choices, default=SyncFrequency.DAILY, blank=True)
    )
    sync_frequency_interval = models.DurationField(default=timedelta(hours=6), null=True, blank=True)

    __repr__ = sane_repr("name")

    @property
    def is_incremental(self):
        return self.sync_type == self.SyncType.INCREMENTAL

    def soft_delete(self):
        self.deleted = True
        self.deleted_at = datetime.now()
        self.save()


@database_sync_to_async
def asave_external_data_schema(schema: ExternalDataSchema) -> None:
    schema.save()


def get_schema_if_exists(schema_name: str, team_id: int, source_id: uuid.UUID) -> ExternalDataSchema | None:
    schema = (
        ExternalDataSchema.objects.exclude(deleted=True)
        .filter(team_id=team_id, source_id=source_id, name=schema_name)
        .first()
    )
    return schema


@database_sync_to_async
def aget_schema_if_exists(schema_name: str, team_id: int, source_id: uuid.UUID) -> ExternalDataSchema | None:
    return get_schema_if_exists(schema_name=schema_name, team_id=team_id, source_id=source_id)


@database_sync_to_async
def aget_schema_by_id(schema_id: str, team_id: int) -> ExternalDataSchema | None:
    return ExternalDataSchema.objects.prefetch_related("source").get(id=schema_id, team_id=team_id)


@database_sync_to_async
def aupdate_should_sync(schema_id: str, team_id: int, should_sync: bool) -> ExternalDataSchema | None:
    schema = ExternalDataSchema.objects.get(id=schema_id, team_id=team_id)
    schema.should_sync = should_sync
    schema.save()

    schedule_exists = external_data_workflow_exists(schema_id)

    if schedule_exists:
        if should_sync is False:
            pause_external_data_schedule(schema_id)
        elif should_sync is True:
            unpause_external_data_schedule(schema_id)
    else:
        if should_sync is True:
            sync_external_data_job_workflow(schema, create=True)

    return schema


@database_sync_to_async
def get_active_schemas_for_source_id(source_id: uuid.UUID, team_id: int):
    return list(
        ExternalDataSchema.objects.exclude(deleted=True)
        .filter(team_id=team_id, source_id=source_id, should_sync=True)
        .all()
    )


def get_all_schemas_for_source_id(source_id: uuid.UUID, team_id: int):
    return list(ExternalDataSchema.objects.exclude(deleted=True).filter(team_id=team_id, source_id=source_id).all())


def sync_old_schemas_with_new_schemas(new_schemas: list, source_id: uuid.UUID, team_id: int):
    old_schemas = get_all_schemas_for_source_id(source_id=source_id, team_id=team_id)
    old_schemas_names = [schema.name for schema in old_schemas]

    schemas_to_create = [schema for schema in new_schemas if schema not in old_schemas_names]

    for schema in schemas_to_create:
        ExternalDataSchema.objects.create(name=schema, team_id=team_id, source_id=source_id, should_sync=False)


def sync_frequency_to_sync_frequency_interval(frequency: str) -> timedelta:
    if frequency == "5min":
        return timedelta(minutes=5)
    if frequency == "30min":
        return timedelta(minutes=30)
    if frequency == "1hour":
        return timedelta(hours=1)
    if frequency == "6hour":
        return timedelta(hours=6)
    if frequency == "12hour":
        return timedelta(hours=12)
    if frequency == "24hour":
        return timedelta(hours=24)
    if frequency == "7day":
        return timedelta(days=7)
    if frequency == "30day":
        return timedelta(days=30)

    raise ValueError(f"Frequency {frequency} is not supported")


def sync_frequency_interval_to_sync_frequency(schema: ExternalDataSchema) -> str:
    if schema.sync_frequency_interval == timedelta(minutes=5):
        return "5min"
    if schema.sync_frequency_interval == timedelta(minutes=30):
        return "30min"
    if schema.sync_frequency_interval == timedelta(hours=1):
        return "1hour"
    if schema.sync_frequency_interval == timedelta(hours=6):
        return "6hour"
    if schema.sync_frequency_interval == timedelta(hours=12):
        return "12hour"
    if schema.sync_frequency_interval == timedelta(hours=24):
        return "24hour"
    if schema.sync_frequency_interval == timedelta(days=7):
        return "7day"
    if schema.sync_frequency_interval == timedelta(days=30):
        return "30day"

    raise ValueError(f"Frequency interval {schema.sync_frequency_interval} is not supported")


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


def filter_mysql_incremental_fields(columns: list[tuple[str, str]]) -> list[tuple[str, IncrementalFieldType]]:
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, type in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date))
        elif type == "datetime":
            results.append((column_name, IncrementalFieldType.DateTime))
        elif type == "tinyint" or type == "smallint" or type == "mediumint" or type == "int" or type == "bigint":
            results.append((column_name, IncrementalFieldType.Integer))

    return results


def get_mysql_schemas(
    host: str,
    port: str,
    database: str,
    user: str,
    password: str,
    schema: str,
    ssh_tunnel: SSHTunnel,
) -> dict[str, list[tuple[str, str]]]:
    def get_schemas(mysql_host: str, mysql_port: int):
        connection = pymysql.connect(
            host=mysql_host,
            port=mysql_port,
            database=database,
            user=user,
            password=password,
            connect_timeout=5,
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


def get_sql_schemas_for_source_type(
    source_type: ExternalDataSource.Type,
    host: str,
    port: str,
    database: str,
    user: str,
    password: str,
    schema: str,
    ssh_tunnel: SSHTunnel,
) -> dict[str, list[tuple[str, str]]]:
    if source_type == ExternalDataSource.Type.POSTGRES:
        schemas = get_postgres_schemas(host, port, database, user, password, schema, ssh_tunnel)
    elif source_type == ExternalDataSource.Type.MYSQL:
        schemas = get_mysql_schemas(host, port, database, user, password, schema, ssh_tunnel)
    else:
        raise Exception("Unsupported source_type")

    return schemas
