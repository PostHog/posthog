from __future__ import annotations

import collections
import math
import re
from collections.abc import Iterator
from typing import Any

import pyarrow as pa
import pymysql
import pymysql.converters
from django.conf import settings
from dlt.common.normalizers.naming.snake_case import NamingConvention
from pymysql.cursors import Cursor, SSCursor

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.helpers import (
    incremental_type_to_initial_value,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_NUMERIC_PRECISION,
    DEFAULT_NUMERIC_SCALE,
    DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
    build_pyarrow_decimal_type,
    table_from_iterator,
)
from posthog.temporal.data_imports.pipelines.source import config
from posthog.temporal.data_imports.pipelines.source.sql import Column, Table
from posthog.temporal.data_imports.pipelines.pipeline.consts import (
    DEFAULT_CHUNK_SIZE,
)
from posthog.warehouse.models.ssh_tunnel import SSHTunnel, SSHTunnelConfig
from posthog.warehouse.types import IncrementalFieldType, PartitionSettings


@config.config
class MySQLSourceConfig(config.Config):
    host: str
    user: str
    password: str
    database: str
    schema: str
    port: int = config.value(converter=int)
    using_ssl: bool = True
    ssh_tunnel: SSHTunnelConfig | None = None


def get_schemas(config: MySQLSourceConfig) -> dict[str, list[tuple[str, str]]]:
    """Get all tables from MySQL source schemas to sync."""

    def inner(mysql_host: str, mysql_port: int):
        ssl_ca: str | None = None

        if config.using_ssl:
            ssl_ca = "/etc/ssl/cert.pem" if settings.DEBUG else "/etc/ssl/certs/ca-certificates.crt"

        connection = pymysql.connect(
            host=mysql_host,
            port=mysql_port,
            database=config.database,
            user=config.user,
            password=config.password,
            connect_timeout=5,
            ssl_ca=ssl_ca,
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = %(schema)s ORDER BY table_name ASC",
                {"schema": config.schema},
            )
            result = cursor.fetchall()

            schema_list = collections.defaultdict(list)
            for row in result:
                schema_list[row[0]].append((row[1], row[2]))

        connection.close()

        return schema_list

    if config.ssh_tunnel and config.ssh_tunnel.enabled:
        ssh_tunnel = SSHTunnel.from_config(config.ssh_tunnel)
        with ssh_tunnel.get_tunnel(config.host, config.port) as tunnel:
            if tunnel is None:
                raise Exception("Can't open tunnel to SSH server")

            return inner(tunnel.local_bind_host, tunnel.local_bind_port)

    return inner(config.host, config.port)


def _sanitize_identifier(identifier: str) -> str:
    if not identifier.isidentifier():
        # Allow identifiers of just numbers
        if re.match("^\\d+$", identifier):
            return f"`{identifier}`"

        if identifier.startswith("$") or (len(identifier) > 0 and identifier[0].isdigit()):
            if not identifier[1:].replace(".", "").replace("_", "").replace("-", "").isidentifier():
                raise ValueError(f"Invalid SQL identifier: {identifier}")

    if not identifier.replace(".", "").replace("_", "").replace("-", "").replace("$", "").isalnum():
        raise ValueError(f"Invalid SQL identifier: {identifier}")

    return f"`{identifier}`"


def _build_query(
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: str | None,
    incremental_field_type: IncrementalFieldType | None,
    db_incremental_field_last_value: Any | None,
) -> tuple[str, dict[str, Any]]:
    query = f"SELECT * FROM `{schema}`.`{table_name}`"

    if not should_use_incremental_field:
        return query, {}

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    query = f"SELECT * FROM {_sanitize_identifier(schema)}.{_sanitize_identifier(table_name)} WHERE {_sanitize_identifier(incremental_field)} >= %(incremental_value)s ORDER BY {_sanitize_identifier(incremental_field)} ASC"

    return query, {
        "incremental_value": db_incremental_field_last_value,
    }


def _get_rows_to_sync(
    cursor: Cursor, inner_query: str, inner_query_args: dict[str, Any], logger: FilteringBoundLogger
) -> int:
    try:
        query = f"SELECT COUNT(*) FROM ({inner_query}) as t"

        cursor.execute(query, inner_query_args)
        row = cursor.fetchone()

        if row is None:
            logger.debug(f"_get_rows_to_sync: No results returned. Using 0 as rows to sync")
            return 0

        rows_to_sync = row[0] or 0
        rows_to_sync_int = int(rows_to_sync)

        logger.debug(f"_get_rows_to_sync: rows_to_sync_int={rows_to_sync_int}")

        return int(rows_to_sync)
    except Exception as e:
        logger.debug(f"_get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
        capture_exception(e)

        return 0


def _get_partition_settings(
    cursor: Cursor, schema: str, table_name: str, partition_size_bytes: int = DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES
) -> PartitionSettings | None:
    """Get partition settings for given MySQL table.

    To obtain partition settings, we look up `DATA_LENGTH` from
    `INFORMATION_SCHEMA.TABLES`. Keep in mind that `DATA_LENGTH` only includes
    size of values in clustered index. Notably, types like `TEXT` do not store
    their values in the index, so the size will be underestimated if fields like
    that are present. This could lead to larger than expected partitions.

    We obtain the row count by counting the table directly, as `TABLE_ROWS` can
    be out of date by a large factor depending on how recently have table
    statistics been computed.
    """
    query = """
    SELECT
        t.DATA_LENGTH AS table_size,
        (SELECT COUNT(*) FROM `{schema_identifier}`.`{table_name_identifier}`) AS row_count
    FROM
        information_schema.TABLES AS t
    WHERE
        t.TABLE_SCHEMA = %(schema)s
        AND t.TABLE_NAME = %(table_name)s
    """.format(
        schema_identifier=pymysql.converters.escape_string(schema),
        table_name_identifier=pymysql.converters.escape_string(table_name),
    )

    cursor.execute(
        query,
        {
            "schema": schema,
            "table_name": table_name,
        },
    )
    result = cursor.fetchone()
    if result is None:
        return None

    table_size, row_count = result

    if table_size is None or row_count is None or row_count == 0:
        return None

    avg_row_size = table_size / row_count
    # Partition must have at least one row
    partition_size = max(round(partition_size_bytes / avg_row_size), 1)
    partition_count = math.floor(row_count / partition_size)

    if partition_count == 0:
        return PartitionSettings(partition_count=1, partition_size=partition_size)

    return PartitionSettings(partition_count=partition_count, partition_size=partition_size)


def _get_primary_keys(cursor: Cursor, schema: str, table_name: str) -> list[str] | None:
    query = """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %(schema)s
        AND TABLE_NAME = %(table_name)s
        AND COLUMN_KEY = 'PRI'"""

    cursor.execute(
        query,
        {
            "schema": schema,
            "table_name": table_name,
        },
    )
    rows = cursor.fetchall()
    if len(rows) > 0:
        return [row[0] for row in rows]

    return None


class MySQLColumn(Column):
    """Implementation of the `Column` protocol for a MySQL source.

    Attributes:
        name: The column's name.
        data_type: The name of the column's data type as described in
            https://www.postgresql.org/docs/current/datatype.html.
        column_type:
        nullable: Whether the column is nullable or not.
        numeric_precision: The number of significant digits. Only used with
            numeric `data_type`s, otherwise `None`.
        numeric_scale: The number of significant digits to the right of
            decimal point. Only used with numeric `data_type`s, otherwise
            `None`.
    """

    def __init__(
        self,
        name: str,
        data_type: str,
        column_type: str,
        nullable: bool,
        numeric_precision: int | None = None,
        numeric_scale: int | None = None,
    ) -> None:
        self.name = name
        self.data_type = data_type
        self.column_type = column_type
        self.nullable = nullable
        self.numeric_precision = numeric_precision
        self.numeric_scale = numeric_scale

    def to_arrow_field(self) -> pa.Field[pa.DataType]:
        """Return a `pyarrow.Field` that closely matches this column."""
        arrow_type: pa.DataType

        # Note that deltalake doesn't support unsigned types, so we need to convert integer types to larger types
        # For example an uint32 should support values up to 2^32, but deltalake will only support 2^31
        # so in order to support unsigned types we need to convert to int64
        is_unsigned = "unsigned" in self.column_type

        # Map MySQL type names to PyArrow types
        match self.data_type.lower():
            case "bigint":
                # There's no larger type than (u)int64
                arrow_type = pa.uint64() if is_unsigned else pa.int64()
            case "int" | "integer" | "mediumint":
                arrow_type = pa.uint64() if is_unsigned else pa.int32()
            case "smallint":
                arrow_type = pa.uint32() if is_unsigned else pa.int16()
            case "tinyint":
                arrow_type = pa.uint16() if is_unsigned else pa.int8()
            case "decimal" | "numeric":
                if not self.numeric_precision or not self.numeric_scale:
                    raise TypeError("expected `numeric_precision` and `numeric_scale` to be `int`, got `NoneType`")

                arrow_type = build_pyarrow_decimal_type(self.numeric_precision, self.numeric_scale)
            case "float":
                arrow_type = pa.float32()
            case "double" | "double precision":
                arrow_type = pa.float64()
            case "varchar" | "char" | "text" | "mediumtext" | "longtext":
                arrow_type = pa.string()
            case "date":
                arrow_type = pa.date32()
            case "datetime" | "timestamp":
                arrow_type = pa.timestamp("us")
            case "time":
                arrow_type = pa.time64("us")
            case "boolean" | "bool":
                arrow_type = pa.bool_()
            case "binary" | "varbinary" | "blob" | "mediumblob" | "longblob":
                arrow_type = pa.binary()
            case "uuid":
                arrow_type = pa.string()
            case "json":
                arrow_type = pa.string()
            case _ if self.data_type.endswith("[]"):  # Array types (though not native in MySQL)
                arrow_type = pa.string()
            case _:
                arrow_type = pa.string()

        return pa.field(self.name, arrow_type, nullable=self.nullable)


def _get_table(cursor: Cursor, schema: str, table_name: str) -> Table[MySQLColumn]:
    query = """
        SELECT
            column_name,
            data_type,
            column_type,
            is_nullable,
            numeric_precision,
            numeric_scale
        FROM
            information_schema.columns
        WHERE
            table_schema = %(schema)s
            AND table_name = %(table_name)s"""

    cursor.execute(
        query,
        {
            "schema": schema,
            "table_name": table_name,
        },
    )

    numeric_data_types = {"numeric", "decimal"}
    columns = []
    for name, data_type, column_type, nullable, numeric_precision_candidate, numeric_scale_candidate in cursor:
        if data_type in numeric_data_types:
            numeric_precision = numeric_precision_candidate or DEFAULT_NUMERIC_PRECISION
            numeric_scale = numeric_scale_candidate or DEFAULT_NUMERIC_SCALE
        else:
            numeric_precision = None
            numeric_scale = None

        columns.append(
            MySQLColumn(
                name=name,
                data_type=data_type,
                column_type=column_type,
                nullable=nullable,
                numeric_precision=numeric_precision,
                numeric_scale=numeric_scale,
            )
        )

    return Table(
        name=table_name,
        parents=(schema,),
        columns=columns,
    )


def mysql_source(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    using_ssl: bool,
    schema: str,
    table_names: list[str],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Any | None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    table_name = table_names[0]
    if not table_name:
        raise ValueError("Table name is missing")

    ssl_ca: str | None = None

    if using_ssl:
        ssl_ca = "/etc/ssl/cert.pem" if settings.DEBUG else "/etc/ssl/certs/ca-certificates.crt"

    with pymysql.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        connect_timeout=5,
        ssl_ca=ssl_ca,
    ) as connection:
        with connection.cursor() as cursor:
            inner_query, inner_query_args = _build_query(
                schema,
                table_name,
                should_use_incremental_field,
                incremental_field,
                incremental_field_type,
                db_incremental_field_last_value,
            )

            primary_keys = _get_primary_keys(cursor, schema, table_name)
            table = _get_table(cursor, schema, table_name)
            rows_to_sync = _get_rows_to_sync(cursor, inner_query, inner_query_args, logger)
            partition_settings = (
                _get_partition_settings(cursor, schema, table_name) if should_use_incremental_field else None
            )

            # Fallback on checking for an `id` field on the table
            if primary_keys is None and "id" in table:
                primary_keys = ["id"]

    def get_rows() -> Iterator[Any]:
        arrow_schema = table.to_arrow_schema()

        # PlanetScale needs this to be set
        init_command = "SET workload = 'OLAP';" if host.endswith("psdb.cloud") else None

        with pymysql.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            connect_timeout=5,
            ssl_ca=ssl_ca,
            init_command=init_command,
        ) as connection:
            with connection.cursor(SSCursor) as cursor:
                query, args = _build_query(
                    schema,
                    table_name,
                    should_use_incremental_field,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                )
                logger.debug(f"MySQL query: {query.format(args)}")

                cursor.execute(query, args)

                column_names = [column[0] for column in cursor.description or []]

                while True:
                    rows = cursor.fetchmany(DEFAULT_CHUNK_SIZE)
                    if not rows:
                        break

                    yield table_from_iterator((dict(zip(column_names, row)) for row in rows), arrow_schema)

    name = NamingConvention().normalize_identifier(table_name)

    return SourceResponse(
        name=name,
        items=get_rows(),
        primary_keys=primary_keys,
        partition_count=partition_settings.partition_count if partition_settings else None,
        partition_size=partition_settings.partition_size if partition_settings else None,
        rows_to_sync=rows_to_sync,
    )
