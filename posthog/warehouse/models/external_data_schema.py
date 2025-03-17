from collections import defaultdict
from datetime import datetime, timedelta
import tempfile
import os
from typing import Any, Optional
from django.db import models
from django_deprecate_fields import deprecate_field
import numpy
import snowflake.connector
from django.conf import settings
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UUIDModel, UpdatedMetaFields, sane_repr
import uuid
import psycopg2
from psycopg2 import sql
import pymysql

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionMode
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
from dlt.common.normalizers.naming.snake_case import NamingConvention


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
    # { "incremental_field": string, "incremental_field_type": string, "incremental_field_last_value": any, "reset_pipeline": bool, "partitioning_enabled": bool, "partition_count": int, "partition_size": int, "partition_mode": str, "partitioning_keys": list[str] }
    sync_type_config = models.JSONField(
        default=dict,
        blank=True,
    )
    # Deprecated in favour of `sync_frequency_interval`
    sync_frequency = deprecate_field(
        models.CharField(max_length=128, choices=SyncFrequency.choices, default=SyncFrequency.DAILY, blank=True)
    )
    sync_frequency_interval = models.DurationField(default=timedelta(hours=6), null=True, blank=True)
    sync_time_of_day = models.TimeField(null=True, blank=True, help_text="Time of day to run the sync (UTC)")

    __repr__ = sane_repr("name")

    def folder_path(self) -> str:
        return f"team_{self.team_id}_{self.source.source_type}_{str(self.id)}".lower().replace("-", "_")

    @property
    def normalized_name(self):
        return NamingConvention().normalize_identifier(self.name)

    @property
    def is_incremental(self):
        return self.sync_type == self.SyncType.INCREMENTAL

    @property
    def incremental_field(self) -> str | None:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field", None)

        return None

    @property
    def incremental_field_type(self) -> str | None:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field_type", None)

        return None

    @property
    def incremental_field_last_value(self) -> str | None:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field_last_value", None)

        return None

    @property
    def reset_pipeline(self) -> bool:
        if self.sync_type_config:
            value = self.sync_type_config.get("reset_pipeline", None)
            if value is None:
                return False

            if value is True or (isinstance(value, str) and value.lower() == "true"):
                return True

        return False

    @property
    def partitioning_enabled(self) -> bool:
        if self.sync_type_config:
            value = self.sync_type_config.get("partitioning_enabled", None)
            if value is None:
                return False

            if value is True or (isinstance(value, str) and value.lower() == "true"):
                return True

        return False

    @property
    def partition_count(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partition_count", None)

        return None

    @property
    def partition_size(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partition_size", None)

        return None

    @property
    def partition_mode(self) -> PartitionMode | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partition_mode", None)

        return None

    @property
    def partitioning_keys(self) -> list[str] | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partitioning_keys", None)

        return None

    def set_partitioning_enabled(
        self,
        partitioning_keys: list[str],
        partition_count: int,
        partition_size: int,
        partition_mode: PartitionMode,
    ) -> None:
        self.sync_type_config["partitioning_enabled"] = True
        self.sync_type_config["partition_count"] = partition_count
        self.sync_type_config["partition_size"] = partition_size
        self.sync_type_config["partitioning_keys"] = partitioning_keys
        self.sync_type_config["partition_mode"] = partition_mode
        self.save()

    def update_sync_type_config_for_reset_pipeline(self) -> None:
        self.sync_type_config.pop("reset_pipeline", None)
        self.sync_type_config.pop("incremental_field_last_value", None)
        self.sync_type_config.pop("partitioning_enabled", None)
        self.sync_type_config.pop("partition_size", None)
        self.sync_type_config.pop("partition_count", None)
        self.sync_type_config.pop("partitioning_keys", None)
        self.sync_type_config.pop("partition_mode", None)

        self.save()

    def update_incremental_field_last_value(self, last_value: Any, save: bool = True) -> None:
        incremental_field_type = self.sync_type_config.get("incremental_field_type")

        last_value_py = last_value.item() if isinstance(last_value, numpy.generic) else last_value
        last_value_json: Any

        if last_value_py is None:
            return

        if (
            incremental_field_type == IncrementalFieldType.Integer
            or incremental_field_type == IncrementalFieldType.Numeric
        ):
            if isinstance(last_value_py, int | float):
                last_value_json = last_value_py
            elif isinstance(last_value_py, datetime):
                last_value_json = last_value_py.isoformat()
            else:
                last_value_json = int(last_value_py)
        elif (
            incremental_field_type == IncrementalFieldType.DateTime
            or incremental_field_type == IncrementalFieldType.Timestamp
        ):
            if isinstance(last_value_py, datetime):
                last_value_json = last_value_py.isoformat()
            else:
                last_value_json = str(last_value_py)
        else:
            last_value_json = str(last_value_py)

        self.sync_type_config["incremental_field_last_value"] = last_value_json

        if save:
            self.save()

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
    return (
        ExternalDataSchema.objects.prefetch_related("source").exclude(deleted=True).get(id=schema_id, team_id=team_id)
    )


def update_should_sync(schema_id: str, team_id: int, should_sync: bool) -> ExternalDataSchema | None:
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


def get_all_schemas_for_source_id(source_id: uuid.UUID, team_id: int):
    return list(ExternalDataSchema.objects.exclude(deleted=True).filter(team_id=team_id, source_id=source_id).all())


def sync_old_schemas_with_new_schemas(new_schemas: list[str], source_id: uuid.UUID, team_id: int) -> list[str]:
    old_schemas = get_all_schemas_for_source_id(source_id=source_id, team_id=team_id)
    old_schemas_names = [schema.name for schema in old_schemas]

    schemas_to_create = [schema for schema in new_schemas if schema not in old_schemas_names]

    for schema in schemas_to_create:
        ExternalDataSchema.objects.create(name=schema, team_id=team_id, source_id=source_id, should_sync=False)

    return schemas_to_create


def sync_frequency_to_sync_frequency_interval(frequency: str) -> timedelta | None:
    if frequency == "never":
        return None
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


def sync_frequency_interval_to_sync_frequency(sync_frequency_interval: timedelta | None) -> str | None:
    if sync_frequency_interval is None:
        return None
    if sync_frequency_interval == timedelta(minutes=5):
        return "5min"
    if sync_frequency_interval == timedelta(minutes=30):
        return "30min"
    if sync_frequency_interval == timedelta(hours=1):
        return "1hour"
    if sync_frequency_interval == timedelta(hours=6):
        return "6hour"
    if sync_frequency_interval == timedelta(hours=12):
        return "12hour"
    if sync_frequency_interval == timedelta(hours=24):
        return "24hour"
    if sync_frequency_interval == timedelta(days=7):
        return "7day"
    if sync_frequency_interval == timedelta(days=30):
        return "30day"

    raise ValueError(f"Frequency interval {sync_frequency_interval} is not supported")


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
    account_id: str,
    database: str,
    warehouse: str,
    user: Optional[str],
    password: Optional[str],
    passphrase: Optional[str],
    private_key: Optional[str],
    auth_type: str,
    schema: str,
    role: Optional[str] = None,
) -> dict[str, list[tuple[str, str]]]:
    auth_connect_args: dict[str, str | None] = {}
    file_name: str | None = None

    if auth_type == "keypair" and private_key is not None:
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(private_key.encode("utf-8"))
            file_name = tf.name

        auth_connect_args = {
            "user": user,
            "private_key_file": file_name,
            "private_key_file_pwd": passphrase,
        }
    else:
        auth_connect_args = {
            "password": password,
            "user": user,
        }

    with snowflake.connector.connect(
        account=account_id,
        warehouse=warehouse,
        database=database,
        schema="information_schema",
        role=role,
        **auth_connect_args,
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

    if file_name is not None:
        os.unlink(file_name)

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


def get_postgres_row_count(
    host: str, port: str, database: str, user: str, password: str, schema: str, ssh_tunnel: SSHTunnel
) -> dict[str, int]:
    def get_row_count(postgres_host: str, postgres_port: int):
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

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT tablename as table_name FROM pg_tables WHERE schemaname = %(schema)s",
                    {"schema": schema},
                )
                tables = cursor.fetchall()

                if not tables:
                    return {}

                counts = [
                    sql.SQL("SELECT {table_name} AS table_name, COUNT(*) AS row_count FROM {schema}.{table}").format(
                        table_name=sql.Literal(table[0]), schema=sql.Identifier(schema), table=sql.Identifier(table[0])
                    )
                    for table in tables
                ]

                union_counts = sql.SQL(" UNION ALL ").join(counts)
                cursor.execute(union_counts)
                row_count_result = cursor.fetchall()
                row_counts = {row[0]: row[1] for row in row_count_result}
            return row_counts
        finally:
            connection.close()

    if ssh_tunnel.enabled:
        with ssh_tunnel.get_tunnel(host, int(port)) as tunnel:
            if tunnel is None:
                raise Exception("Can't open tunnel to SSH server")

            return get_row_count(tunnel.local_bind_host, tunnel.local_bind_port)

    return get_row_count(host, int(port))


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
    using_ssl: bool,
    ssh_tunnel: SSHTunnel,
) -> dict[str, list[tuple[str, str]]]:
    def get_schemas(mysql_host: str, mysql_port: int):
        ssl_ca: str | None = None

        if using_ssl:
            ssl_ca = "/etc/ssl/cert.pem" if settings.DEBUG else "/etc/ssl/certs/ca-certificates.crt"

        connection = pymysql.connect(
            host=mysql_host,
            port=mysql_port,
            database=database,
            user=user,
            password=password,
            connect_timeout=5,
            ssl_ca=ssl_ca,
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


def filter_mssql_incremental_fields(columns: list[tuple[str, str]]) -> list[tuple[str, IncrementalFieldType]]:
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, type in columns:
        type = type.lower()
        if type == "date":
            results.append((column_name, IncrementalFieldType.Date))
        elif type == "datetime" or type == "datetime2" or type == "smalldatetime":
            results.append((column_name, IncrementalFieldType.DateTime))
        elif type == "tinyint" or type == "smallint" or type == "int" or type == "bigint":
            results.append((column_name, IncrementalFieldType.Integer))

    return results


def get_mssql_schemas(
    host: str, port: str, database: str, user: str, password: str, schema: str, ssh_tunnel: SSHTunnel
) -> dict[str, list[tuple[str, str]]]:
    def get_schemas(mssql_host: str, mssql_port: int):
        # Importing pymssql requires mssql drivers to be installed locally - see posthog/warehouse/README.md
        import pymssql

        connection = pymssql.connect(
            server=mssql_host,
            port=str(mssql_port),
            database=database,
            user=user,
            password=password,
            login_timeout=5,
        )

        with connection.cursor(as_dict=False) as cursor:
            cursor.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = %(schema)s ORDER BY table_name ASC",
                {"schema": schema},
            )

            schema_list = defaultdict(list)

            for row in cursor:
                if row:
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
    using_ssl: bool = True,
) -> dict[str, list[tuple[str, str]]]:
    if source_type == ExternalDataSource.Type.POSTGRES:
        schemas = get_postgres_schemas(host, port, database, user, password, schema, ssh_tunnel)
    elif source_type == ExternalDataSource.Type.MYSQL:
        schemas = get_mysql_schemas(host, port, database, user, password, schema, using_ssl, ssh_tunnel)
    elif source_type == ExternalDataSource.Type.MSSQL:
        schemas = get_mssql_schemas(host, port, database, user, password, schema, ssh_tunnel)
    else:
        raise Exception("Unsupported source_type")

    return schemas
