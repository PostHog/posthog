import io
import json
import typing
import asyncio
import datetime as dt
import contextlib
import dataclasses
import collections.abc

from django.conf import settings

import pyarrow as pa
from google.api_core.exceptions import Forbidden, NotFound
from google.cloud import bigquery
from google.oauth2 import service_account
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportInsertInputs,
    BatchExportModel,
    BatchExportSchema,
    BigQueryBatchExportInputs,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.temporal.batch_exports import (
    OverBillingLimitError,
    StartBatchExportRunInputs,
    default_fields,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.heartbeat import BatchExportRangeHeartbeatDetails
from products.batch_exports.backend.temporal.pipeline.consumer import Consumer, run_consumer_from_stage
from products.batch_exports.backend.temporal.pipeline.entrypoint import execute_batch_export_using_internal_stage
from products.batch_exports.backend.temporal.pipeline.producer import Producer
from products.batch_exports.backend.temporal.pipeline.table import (
    TIMESTAMP_MS_TO_SECONDS_SINCE_EPOCH,
    Field,
    Table,
    TableReference,
    _noop_cast,
)
from products.batch_exports.backend.temporal.pipeline.transformer import (
    ChunkTransformerProtocol,
    JSONLStreamTransformer,
    ParquetStreamTransformer,
    PipelineTransformer,
    SchemaTransformer,
)
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, wait_for_schema_or_producer
from products.batch_exports.backend.temporal.utils import JsonType, handle_non_retryable_errors

NON_RETRYABLE_ERROR_TYPES = (
    # Raised on missing permissions.
    "Forbidden",
    # Invalid token.
    "RefreshError",
    # Usually means the dataset or project_id doesn't exist.
    # "NotFound",
    # Raised when something about dataset is wrong (not alphanumeric, too long, etc).
    # "BadRequest",
    # Raised when table_id isn't valid. Sadly, `ValueError` is rather generic, but we
    # don't anticipate a `ValueError` thrown from our own export code.
    # "ValueError",
    # Raised when attempting to run a batch export without required BigQuery permissions.
    # Our own version of `Forbidden`.
    "MissingRequiredPermissionsError",
)

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger("EXTERNAL")

COMPATIBLE_TYPES = {
    # BigQuery doesn't have a unsigned type, so we hope we don't overflow.
    # We could cast here and fail if the value overflows, but historically this hasn't
    # come up.
    (pa.uint64(), pa.int64()): _noop_cast,
    # BigQuery doesn't have an int smaller than 'INT64', but can take any smaller number
    # as an 'INT64', so we don't need to cast. No risk of overflow here.
    (pa.uint8(), pa.int64()): _noop_cast,
    # BigQuery deals with timestamps in microseconds, but it does interpret timestamps
    # in milliseconds correctly, so we don't need to cast.
    (pa.timestamp("ms", tz="UTC"), pa.timestamp("us", tz="UTC")): _noop_cast,
    # We assume this is a destination field created from a ClickHouse `DateTime` that
    # has  been updated to `DateTime64(3)`.
    # This would mean the field would have been created as a BigQuery 'INT64', but we
    # are now receiving a `pa.timestamp("ms", tz="UTC")`.
    # So, since `DateTime` is seconds since the EPOCH, we maintain that here.
    # This technically truncates the millisecond part of the value, but if it came from
    # a `DateTime` then we assume it is empty (as it would have been empty before).
    (pa.timestamp("ms", tz="UTC"), pa.int64()): TIMESTAMP_MS_TO_SECONDS_SINCE_EPOCH,
}

FileFormat = typing.Literal["Parquet", "JSONLines"]
BigQueryTypeName = typing.Literal[
    "JSON",
    "STRING",
    "INT64",
    "BOOL",
    "BOOLEAN",  # Alias of 'BOOL'
    "FLOAT64",
    "FLOAT",  # Undocumented alias of 'FLOAT64'
    "BYTES",
    "TIMESTAMP",
    # The next 'INT'-like that follow are aliases of 'INT64'
    # Don't ask me why they need 6 of them.
    "INT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "TINYINT",
    "BYTEINT",
]


class BigQueryType(typing.NamedTuple):
    name: BigQueryTypeName
    repeated: bool


def bigquery_type_to_data_type(type: BigQueryType) -> pa.DataType:
    """Mapping of `BigQueryType` to corresponding `pa.DataType`."""
    match type.name:
        case "STRING":
            base_type = pa.string()
        case "JSON":
            base_type = JsonType()
        case "INT64" | "INT" | "SMALLINT" | "INTEGER" | "BIGINT" | "TINYINT" | "BYTEINT":
            base_type = pa.int64()
        case "BOOL" | "BOOLEAN":
            base_type = pa.bool_()
        case "FLOAT64" | "FLOAT":
            base_type = pa.float64()
        case "TIMESTAMP":
            # BigQuery uses microsecond precision ('us'), not to be confused with
            # millisecond ('ms').
            # BigQuery's 'TIMESTAMP' does not take a timezone, but rather the internal
            # value is displayed to the user in their own timezone when queried. We
            # work with UTC, we always send them UTC, and assume BigQuery also does.
            base_type = pa.timestamp("us", tz="UTC")
        case "BYTES":
            base_type = pa.binary()
        case _:
            raise ValueError(f"Unsupported type: '{type.name}'")

    if type.repeated is True:
        return pa.list_(base_type)
    else:
        return base_type


def data_type_to_bigquery_type(data_type: pa.DataType) -> BigQueryType:
    """Mapping of `pa.DataType` to corresponding `BigQueryType`."""
    repeated = False

    if pa.types.is_string(data_type):
        bq_type = "STRING"
    elif isinstance(data_type, JsonType):
        bq_type = "JSON"

    elif pa.types.is_binary(data_type):
        bq_type = "BYTES"

    elif pa.types.is_signed_integer(data_type) or pa.types.is_unsigned_integer(data_type):
        # The latter comparison is hoping we don't overflow, but BigQuery doesn't have an uint64 type.
        bq_type = "INT64"

    elif pa.types.is_floating(data_type):
        bq_type = "FLOAT64"

    elif pa.types.is_boolean(data_type):
        bq_type = "BOOL"

    elif pa.types.is_timestamp(data_type):
        bq_type = "TIMESTAMP"

    elif pa.types.is_list(data_type) and pa.types.is_string(data_type.value_type):
        bq_type = "STRING"
        repeated = True

    else:
        raise ValueError(f"Unsupported type '{data_type}'")

    return BigQueryType(name=bq_type, repeated=repeated)


class BigQueryField(Field):
    """A field of a BigQueryTable."""

    def __init__(self, name: str, type: BigQueryType, nullable: bool):
        self.name = name
        self.bigquery_type = type
        self.nullable = nullable
        self.data_type = bigquery_type_to_data_type(type)

    @classmethod
    def from_arrow_field(cls, field: pa.Field) -> typing.Self:
        type = data_type_to_bigquery_type(field.type)
        return cls(field.name, type, nullable=field.nullable)

    def to_arrow_field(self) -> pa.Field:
        return pa.field(self.name, self.data_type)

    @classmethod
    def from_destination_field(cls, field: bigquery.SchemaField) -> typing.Self:
        name = field.name
        type_name = field.field_type

        mode = field.mode
        repeated = mode == "REPEATED"
        nullable = mode == "NULLABLE"

        return cls(name, BigQueryType(type_name, repeated), nullable=nullable)

    def to_destination_field(self) -> bigquery.SchemaField:
        return bigquery.SchemaField(name=self.name, field_type=self.bigquery_type.name, mode=self.mode)

    def with_new_arrow_type(self, new_type: pa.DataType) -> "BigQueryField":
        return BigQueryField(self.name, data_type_to_bigquery_type(new_type), self.nullable)

    @property
    def mode(self) -> typing.Literal["REPEATED", "NULLABLE", "REQUIRED"]:
        if self.bigquery_type.repeated:
            return "REPEATED"
        elif self.nullable:
            return "NULLABLE"
        else:
            return "REQUIRED"


class BigQueryTable(Table[BigQueryField]):
    """A table in BigQuery."""

    def __init__(
        self,
        name: str,
        fields: collections.abc.Iterable[BigQueryField],
        parents: tuple[str, ...] = (),
        primary_key: collections.abc.Iterable[str] = (),
        version_key: collections.abc.Iterable[str] = (),
        time_partitioning: bigquery.table.TimePartitioning | None = None,
    ) -> None:
        super().__init__(name, fields, parents, primary_key, version_key)
        self.time_partitioning = time_partitioning

    @classmethod
    def from_bigquery_table(
        cls,
        table: bigquery.Table,
        primary_key: collections.abc.Iterable[str] = (),
        version_key: collections.abc.Iterable[str] = (),
    ) -> typing.Self:
        name = table.table_id
        parents = (table.project, table.dataset_id)
        fields = tuple(BigQueryField.from_destination_field(field) for field in table.schema)
        time_partitioning = table.time_partitioning

        return cls(name, fields, parents, primary_key, version_key, time_partitioning=time_partitioning)

    @classmethod
    def from_arrow_schema(
        cls,
        schema: pa.Schema,
        project_id: str,
        dataset_id: str,
        table_id: str,
        primary_key: collections.abc.Iterable[str] = (),
        version_key: collections.abc.Iterable[str] = (),
    ) -> typing.Self:
        return cls.from_arrow_schema_full(
            schema,
            BigQueryField,
            table_id,
            (project_id, dataset_id),
            primary_key,
            version_key,
        )

    @property
    def project_id(self) -> str:
        return self.parents[0]

    @property
    def dataset_id(self) -> str:
        return self.parents[1]


class BigQueryClient:
    def __init__(self, client: bigquery.Client):
        self.client = client

        self.logger = LOGGER.bind(project_id=client.project)
        self.external_logger = EXTERNAL_LOGGER.bind(project_id=client.project)

    async def __aenter__(self) -> typing.Self:
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await asyncio.to_thread(self.client.close)
        return None

    @classmethod
    def from_service_account_inputs(
        cls, private_key: str, private_key_id: str, token_uri: str, client_email: str, project_id: str
    ) -> typing.Self:
        credentials = service_account.Credentials.from_service_account_info(
            {
                "private_key": private_key,
                "private_key_id": private_key_id,
                "token_uri": token_uri,
                "client_email": client_email,
                "project_id": project_id,
            },
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        client = bigquery.Client(
            project=project_id,
            credentials=credentials,
        )
        return cls(client)

    async def create_table(
        self,
        table: BigQueryTable | TableReference,
        exists_ok: bool = True,
    ) -> BigQueryTable:
        """Create a table in BigQuery."""
        if isinstance(table, BigQueryTable):
            schema = tuple(field.to_destination_field() for field in table.fields)
        else:
            schema = ()

        bq_table = bigquery.Table(table.fully_qualified_name, schema=schema)

        if isinstance(table, BigQueryTable) and "timestamp" in table:
            # TODO: Maybe choosing which column to use as partitioning should be a configuration parameter.
            # 'timestamp' is used for backwards compatibility.
            bq_table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY, field="timestamp"
            )

        created_bq_table = await asyncio.to_thread(self.client.create_table, bq_table, exists_ok=exists_ok)

        if isinstance(table, BigQueryTable):
            return BigQueryTable.from_bigquery_table(created_bq_table, table.primary_key, table.version_key)
        else:
            return BigQueryTable.from_bigquery_table(created_bq_table)

    async def delete_table(
        self,
        table: BigQueryTable | TableReference,
        not_found_ok: bool = True,
    ) -> None:
        """Delete a table in BigQuery."""
        await asyncio.to_thread(self.client.delete_table, table.fully_qualified_name, not_found_ok=not_found_ok)

        return None

    async def get_table(
        self,
        table: BigQueryTable | TableReference,
    ) -> BigQueryTable:
        """Get a table in BigQuery."""
        bq_table = await asyncio.to_thread(self.client.get_table, table.fully_qualified_name)

        if isinstance(table, BigQueryTable):
            return BigQueryTable.from_bigquery_table(bq_table, table.primary_key, table.version_key)
        else:
            return BigQueryTable.from_bigquery_table(bq_table)

    async def get_or_create_table(
        self,
        table: BigQueryTable | TableReference,
    ) -> BigQueryTable:
        """Get a table in BigQuery."""
        try:
            table = await self.get_table(table)
            return table
        except NotFound:
            table = await self.create_table(table)
            return table

    async def check_for_query_permissions(
        self,
        table: BigQueryTable | TableReference,
    ) -> bool:
        """Attempt to SELECT from table to check for query permissions."""
        job_config = bigquery.QueryJobConfig()

        if isinstance(table, BigQueryTable) and "timestamp" in table:
            query = f"""
            SELECT 1 FROM  `{table.fully_qualified_name}` TABLESAMPLE SYSTEM (0.0001 PERCENT) WHERE timestamp IS NOT NULL
            """

            if table.time_partitioning is not None and table.time_partitioning.field == "timestamp":
                today = dt.date.today()
                query += f" AND DATE(timestamp) = '{today.isoformat()}'"

            query += " LIMIT 1"

        else:
            query = f"""
            SELECT 1 FROM  `{table.fully_qualified_name}` TABLESAMPLE SYSTEM (0.0001 PERCENT) LIMIT 1
            """

        try:
            query_job = self.client.query(query, job_config=job_config)
            await asyncio.to_thread(query_job.result)
        except Forbidden:
            return False
        return True

    @contextlib.asynccontextmanager
    async def managed_table(
        self,
        table: BigQueryTable | TableReference,
        exists_ok: bool = True,
        not_found_ok: bool = True,
        delete: bool = True,
        create: bool = True,
    ) -> collections.abc.AsyncGenerator[BigQueryTable, None]:
        """Manage a table in BigQuery by ensuring it exists while in context."""
        if create is True:
            managed_table = await self.create_table(table, exists_ok)
        else:
            managed_table = await self.get_table(table)

        try:
            yield managed_table
        finally:
            if delete is True:
                try:
                    await self.delete_table(managed_table, not_found_ok)
                except Forbidden:
                    self.external_logger.warning(
                        "Table '%s' may not be properly cleaned up due to missing necessary permissions",
                        managed_table.fully_qualified_name,
                    )

    async def merge_tables(
        self,
        final: BigQueryTable,
        stage: BigQueryTable,
    ):
        """Merge `stage` into `final`.

        This method can execute one of two queries, depending on the type of `final`:
        When it is a `MutableTable`, then it executes a more complex `MERGE` query as it
        needs to mutate fields of any matching rows. In all other cases, a relatively
        simple `INSERT INTO` is executed instead, effectively treating `final` as an
        'append-only' table in which every row is unique.

        Arguments:
            final: The BigQuery table we are merging into.
            stage: The BigQuery table we are merging from.
        """
        if final.is_mutable():
            return await self.merge_into_final_from_stage(
                final,
                stage,
            )
        else:
            return await self.insert_into_final_from_stage(
                final,
                stage,
            )

    async def insert_into_final_from_stage(
        self,
        final: BigQueryTable,
        stage: BigQueryTable,
    ):
        """Insert data from `stage` into `final`."""
        job_config = bigquery.QueryJobConfig()
        into_table_fields = ",".join(f"`{field.name}`" for field in final.fields)

        fields_to_cast = {
            field.name
            for field in final
            if field.bigquery_type.name == "JSON" and stage[field.name].bigquery_type.name != "JSON"
        }

        # The following `REGEXP_REPLACE` functions are used to clean-up un-paired
        # surrogates, as they are rejected by `PARSE_JSON`. Since BigQuery's regex
        # engine has no lookahead / lookback, we instead use an OR to match both
        # valid pairs and invalid single high or low surrogates, and replacing only
        # with the valid pair in both cases.
        stage_table_fields = ",".join(
            f"""
            PARSE_JSON(
              REGEXP_REPLACE(
                REGEXP_REPLACE(
                  REGEXP_REPLACE(
                    `{field.name}`,
                    r'(\\\\u[dD][89A-Fa-f][0-9A-Fa-f]{{2}}\\\\u[dD][c-fC-F][0-9A-Fa-f]{{2}})|(\\\\u[dD][89A-Fa-f][0-9A-Fa-f]{{2}})',
                    '\\\\1'
                  ),
                  r'(\\\\u[dD][89A-Fa-f][0-9A-Fa-f]{{2}}\\\\u[dD][c-fC-F][0-9A-Fa-f]{{2}})|(\\\\u[dD][c-fC-F][0-9A-Fa-f]{{2}})',
                  '\\\\1'
                ),
                r'[\\n\\r]',
                r'\\\\n'
              ),
              wide_number_mode=>'round'
            )
            """
            if field.name in fields_to_cast
            else f"`{field.name}`"
            for field in final.fields
        )

        query = f"""
        INSERT INTO `{final.fully_qualified_name}`
          ({into_table_fields})
        SELECT
          {stage_table_fields}
        FROM `{stage.fully_qualified_name}`
        """

        self.logger.info("Inserting into final table", format=format, table_id=final.name, stage_table_id=stage.name)

        query_job = self.client.query(query, job_config=job_config)
        result = await asyncio.to_thread(query_job.result)
        return result

    async def merge_into_final_from_stage(
        self,
        final: BigQueryTable,
        stage: BigQueryTable,
    ):
        """Merge two identical person model tables in BigQuery."""
        job_config = bigquery.QueryJobConfig()

        fields_to_cast = {
            field.name
            for field in final
            if field.bigquery_type.name == "JSON" and stage[field.name].bigquery_type.name != "JSON"
        }

        merge_condition = "ON "

        for n, field_name in enumerate(final.primary_key):
            if n > 0:
                merge_condition += " AND "
            merge_condition += f"final.`{field_name}` = stage.`{field_name}`"

        update_condition = "AND ("

        for index, field_name in enumerate(final.version_key):
            if index > 0:
                update_condition += " OR "
            update_condition += f"final.`{field_name}` < stage.`{field_name}`"
        update_condition += ")"

        update_clause = ""
        values = ""
        field_names = ""

        for n, field in enumerate(final.fields):
            if n > 0:
                update_clause += ", "
                values += ", "
                field_names += ", "

            # The following `REGEXP_REPLACE` functions are used to clean-up un-paired
            # surrogates, as they are rejected by `PARSE_JSON`. Since BigQuery's regex
            # engine has no lookahead / lookback, we instead use an OR to match both
            # valid pairs and invalid single high or low surrogates, and replacing only
            # with the valid pair in both cases.
            stage_field = (
                f"""
                PARSE_JSON(
                  REGEXP_REPLACE(
                    REGEXP_REPLACE(
                      REGEXP_REPLACE(
                        stage.`{field.name}`,
                        r'(\\\\u[dD][89A-Ba-b][0-9A-Fa-f]{{2}}\\\\u[dD][c-fC-F][0-9A-Fa-f]{{2}})|(\\\\u[dD][89A-Fa-f][0-9A-Fa-f]{{2}})',
                        '\\\\1'
                      ),
                      r'(\\\\u[dD][89A-Ba-b][0-9A-Fa-f]{{2}}\\\\u[dD][c-fC-F][0-9A-Fa-f]{{2}})|(\\\\u[dD][c-fC-F][0-9A-Fa-f]{{2}})',
                      '\\\\1'
                    ),
                    r'[\\n\\r]',
                    r'\\\\n'
                  ),
                  wide_number_mode=>'round'
                )
                """
                if field.name in fields_to_cast
                else f"stage.`{field.name}`"
            )

            update_clause += f"final.`{field.name}` = {stage_field}"
            field_names += f"`{field.name}`"
            values += stage_field

        if not update_clause:
            raise ValueError("Empty update clause")

        merge_query = f"""
        MERGE `{final.fully_qualified_name}` final
        USING (
            SELECT * FROM
            (
              SELECT
              *,
              ROW_NUMBER() OVER (PARTITION BY {",".join(field_name for field_name in final.primary_key)}) row_num
            FROM
              `{stage.fully_qualified_name}`
            )
            WHERE row_num = 1
        ) stage
        {merge_condition}

        WHEN MATCHED {update_condition} THEN
            UPDATE SET
                {update_clause}
        WHEN NOT MATCHED BY TARGET THEN
            INSERT ({field_names})
            VALUES ({values});
        """

        query_job = self.client.query(merge_query, job_config=job_config)
        return await asyncio.to_thread(query_job.result)

    async def load_file(self, file, format: FileFormat, table: BigQueryTable):
        schema = tuple(field.to_destination_field() for field in table.fields)
        if format == "Parquet":
            job_config = bigquery.LoadJobConfig(
                source_format="PARQUET",
                schema=schema,
            )
        elif format == "JSONLines":
            job_config = bigquery.LoadJobConfig(
                source_format="NEWLINE_DELIMITED_JSON",
                schema=schema,
            )
        else:
            raise ValueError(f"Unsupported file format '{format}'")

        self.logger.info("Creating BigQuery load job", format=format, table_id=table.name)

        bq_table = bigquery.Table(table.fully_qualified_name, schema=schema)
        load_job = await asyncio.to_thread(
            self.client.load_table_from_file, file, bq_table, job_config=job_config, rewind=True
        )

        self.logger.info("Waiting for BigQuery load job", format=format, table_id=table.name)

        try:
            result = await asyncio.to_thread(load_job.result)
        except Forbidden as err:
            if err.reason == "quotaExceeded":
                raise BigQueryQuotaExceededError(err.message) from err
            raise

        return result


class MissingRequiredPermissionsError(Exception):
    """Raised when missing required permissions in BigQuery."""

    def __init__(self):
        super().__init__("Missing required permissions to run this batch export")


def get_bigquery_fields_from_record_schema(
    record_schema: pa.Schema, known_json_columns: collections.abc.Sequence[str]
) -> list[bigquery.SchemaField]:
    """Generate a list of supported BigQuery fields from PyArrow schema.

    This function is used to map custom schemas to BigQuery-supported types. Some loss
    of precision is expected.

    Arguments:
        record_schema: The schema of a PyArrow RecordBatch from which we'll attempt to
            derive BigQuery-supported types.
        known_json_columns: If a string type field is a known JSON column then use JSON
            as its BigQuery type.
    """
    bq_schema: list[bigquery.SchemaField] = []

    for name in record_schema.names:
        if name == "_inserted_at":
            continue

        repeated = False
        pa_field = record_schema.field(name)

        if pa.types.is_string(pa_field.type) or isinstance(pa_field.type, JsonType):
            if pa_field.name in known_json_columns:
                bq_type = "JSON"
            else:
                bq_type = "STRING"

        elif pa.types.is_binary(pa_field.type):
            bq_type = "BYTES"

        elif pa.types.is_signed_integer(pa_field.type) or pa.types.is_unsigned_integer(pa_field.type):
            # The latter comparison is hoping we don't overflow, but BigQuery doesn't have an uint64 type.
            bq_type = "INT64"

        elif pa.types.is_floating(pa_field.type):
            bq_type = "FLOAT64"

        elif pa.types.is_boolean(pa_field.type):
            bq_type = "BOOL"

        elif pa.types.is_timestamp(pa_field.type):
            bq_type = "TIMESTAMP"

        elif pa.types.is_list(pa_field.type) and pa.types.is_string(pa_field.type.value_type):
            bq_type = "STRING"
            repeated = True

        else:
            raise TypeError(f"Unsupported type in field '{name}': '{pa_field.type}'")

        bq_schema.append(bigquery.SchemaField(name, bq_type, mode="REPEATED" if repeated else "NULLABLE"))

    return bq_schema


@dataclasses.dataclass
class BigQueryHeartbeatDetails(BatchExportRangeHeartbeatDetails):
    """The BigQuery batch export details included in every heartbeat."""

    pass


@dataclasses.dataclass(kw_only=True)
class BigQueryInsertInputs(BatchExportInsertInputs):
    """Inputs for BigQuery."""

    project_id: str
    dataset_id: str
    table_id: str
    private_key: str
    private_key_id: str
    token_uri: str
    client_email: str
    use_json_type: bool = False


class BigQueryQuotaExceededError(Exception):
    """Exception raised when a BigQuery quota is exceeded.

    This error indicates that we have been exporting too much data and need to
    slow down. This error is retryable.
    """

    def __init__(self, message: str):
        super().__init__(f"A BigQuery quota has been exceeded. Error: {message}")


def bigquery_default_fields() -> list[BatchExportField]:
    """Default fields for a BigQuery batch export.

    Starting from the common default fields, we add and tweak some fields for
    backwards compatibility.
    """
    batch_export_fields = default_fields()
    batch_export_fields.append(
        {
            "expression": "nullIf(JSONExtractString(properties, '$ip'), '')",
            "alias": "ip",
        }
    )
    # Fields kept or removed for backwards compatibility with legacy apps schema.
    batch_export_fields.append({"expression": "toJSONString(elements_chain)", "alias": "elements"})
    batch_export_fields.append({"expression": "''", "alias": "site_url"})
    batch_export_fields.append({"expression": "NOW64()", "alias": "bq_ingested_timestamp"})
    batch_export_fields.pop(batch_export_fields.index({"expression": "created_at", "alias": "created_at"}))

    return batch_export_fields


class BigQueryConsumer(Consumer):
    def __init__(
        self,
        client: BigQueryClient,
        table: BigQueryTable,
        file_format: FileFormat,
    ):
        super().__init__()

        self.client = client
        self.table = table
        self.file_format = file_format

        self.logger = self.logger.bind(table=self.table)

        self.current_file_index = 0
        self.current_buffer = io.BytesIO()

    async def consume_chunk(self, data: bytes):
        self.current_buffer.write(data)
        await asyncio.sleep(0)

    async def finalize_file(self):
        await self._upload_current_buffer()
        self._start_new_file()

    def _start_new_file(self):
        """Start a new file (reset state for file splitting)."""
        self.current_file_index += 1

    async def finalize(self):
        """Finalize by uploading any remaining data."""
        await self._upload_current_buffer()

    async def _upload_current_buffer(self):
        buffer_size = self.current_buffer.tell()
        if buffer_size == 0:
            return

        self.logger.debug(
            "Load job starting",
            current_file_index=self.current_file_index,
            buffer_size=buffer_size,
        )

        await self.client.load_file(self.current_buffer, format=self.file_format, table=self.table)

        self.logger.debug(
            "Load job finished",
            current_file_index=self.current_file_index,
            buffer_size=buffer_size,
        )

        self.current_buffer = io.BytesIO()


class MergeSettings(typing.NamedTuple):
    primary_key: collections.abc.Sequence[str]
    version_key: collections.abc.Sequence[str]


def _get_merge_settings(
    model: BatchExportModel | BatchExportSchema | None,
) -> MergeSettings | None:
    """Return merge settings for models that require merging."""
    if isinstance(model, BatchExportModel):
        if model.name == "persons":
            primary_key = ("team_id", "distinct_id")
            version_key = ("person_version", "person_distinct_id_version")
        elif model.name == "sessions":
            primary_key = ("team_id", "session_id")
            version_key = ("end_timestamp",)
        # TODO: Support merges in 'events'?
        else:
            return None
    else:
        return None

    return MergeSettings(primary_key, version_key)


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_bigquery_activity_from_stage(inputs: BigQueryInsertInputs) -> BatchExportResult:
    """Activity streams data from ClickHouse to BigQuery."""
    bind_contextvars(
        team_id=inputs.team_id,
        destination="BigQuery",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        batch_export_id=inputs.batch_export_id,
        project_id=inputs.project_id,
        dataset_id=inputs.dataset_id,
        table_id=inputs.table_id,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    external_logger.info(
        "Batch exporting range %s - %s to BigQuery: %s.%s.%s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
        inputs.project_id,
        inputs.dataset_id,
        inputs.table_id,
    )

    async with Heartbeater():
        model: BatchExportModel | BatchExportSchema | None = None
        if inputs.batch_export_schema is None:
            model = inputs.batch_export_model
        else:
            model = inputs.batch_export_schema

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_BIGQUERY_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = Producer()
        assert inputs.batch_export_id is not None
        producer_task = await producer.start(
            queue=queue,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=inputs.data_interval_start,
            data_interval_end=inputs.data_interval_end,
            max_record_batch_size_bytes=1024 * 1024 * 60,  # 60MB
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.data_interval_start or "START",
                inputs.data_interval_end or "END",
            )

            return BatchExportResult(records_completed=0, bytes_exported=0)

        record_batch_schema = pa.schema(
            # NOTE: For some reason, some batches set non-nullable fields as non-nullable, whereas other
            # record batches have them as nullable.
            # Until we figure it out, we set all fields to nullable. There are some fields we know
            # are not nullable, but I'm opting for the more flexible option until we out why schemas differ
            # between batches.
            [field.with_nullable(True) for field in record_batch_schema if field.name != "_inserted_at"]
        )
        if inputs.use_json_type:
            # TODO: Figure out which fields are JSON without hard-coding them here.
            json_fields = {"properties", "set", "set_once", "person_properties"}
            record_batch_schema = pa.schema(
                field.with_type(JsonType()) if field.name in json_fields else field for field in record_batch_schema
            )
        else:
            json_fields = set()

        merge_settings = _get_merge_settings(model)
        target_table = BigQueryTable.from_arrow_schema(
            record_batch_schema,
            table_id=inputs.table_id,
            project_id=inputs.project_id,
            dataset_id=inputs.dataset_id,
            primary_key=merge_settings.primary_key,
            version_key=merge_settings.version_key,
        )

        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        attempt = activity.info().attempt
        stage_table_id = f"stage_{inputs.table_id}_{data_interval_end_str}_{inputs.team_id}_{attempt}"

        async with BigQueryClient.from_service_account_inputs(
            inputs.private_key, inputs.private_key_id, inputs.token_uri, inputs.client_email, inputs.project_id
        ) as bq_client:
            bigquery_target_table = await bq_client.get_or_create_table(target_table)

            can_perform_merge = await bq_client.check_for_query_permissions(bigquery_target_table)
            if not can_perform_merge:
                if bigquery_target_table.is_mutable():
                    raise MissingRequiredPermissionsError()

                external_logger.warning(
                    "Missing query permissions on BigQuery table required for merging, will attempt direct load into final table"
                )
                consumer_table = bigquery_target_table
            else:
                consumer_table = BigQueryTable(
                    stage_table_id,
                    bigquery_target_table.fields,
                    bigquery_target_table.parents,
                    primary_key=bigquery_target_table.primary_key,
                    version_key=bigquery_target_table.version_key,
                )

                if inputs.use_json_type:
                    for field_name in json_fields:
                        if field_name not in consumer_table:
                            continue

                        field = consumer_table[field_name]
                        consumer_table[field_name] = field.with_new_arrow_type(pa.string())

            async with bq_client.managed_table(
                table=consumer_table,
                create=can_perform_merge,
                delete=can_perform_merge,
            ) as bigquery_consumer_table:
                consumer = BigQueryConsumer(
                    client=bq_client,
                    table=bigquery_consumer_table,
                    file_format="Parquet" if can_perform_merge else "JSONLines",
                )

                if can_perform_merge:
                    transformer: ChunkTransformerProtocol = PipelineTransformer(
                        transformers=(
                            SchemaTransformer(
                                table=bigquery_consumer_table,
                                extra_compatible_types=COMPATIBLE_TYPES,
                            ),
                            ParquetStreamTransformer(
                                compression="zstd",
                                max_file_size_bytes=settings.BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES,
                            ),
                        )
                    )
                else:
                    transformer = PipelineTransformer(
                        transformers=(
                            SchemaTransformer(
                                table=bigquery_consumer_table,
                                extra_compatible_types=COMPATIBLE_TYPES,
                            ),
                            JSONLStreamTransformer(
                                max_file_size_bytes=settings.BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES
                            ),
                        )
                    )

                result = await run_consumer_from_stage(
                    queue=queue,
                    consumer=consumer,
                    producer_task=producer_task,
                    transformer=transformer,
                    # TODO: Deprecate this argument once all other destinations are also migrated.
                    json_columns=(),
                )

                if can_perform_merge:
                    _ = await bq_client.merge_tables(
                        final=bigquery_target_table,
                        stage=bigquery_consumer_table,
                    )

                return result


@workflow.defn(name="bigquery-export", failure_exception_types=[workflow.NondeterminismError])
class BigQueryBatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into BigQuery.

    This Workflow is intended to be executed both manually and by a Temporal
    Schedule. When ran by a schedule, `data_interval_end` should be set to
    `None` so that we will fetch the end of the interval from the Temporal
    search attribute `TemporalScheduledStartTime`.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BigQueryBatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return BigQueryBatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: BigQueryBatchExportInputs):
        """Workflow implementation to export data to BigQuery."""
        is_backfill = inputs.get_is_backfill()
        is_earliest_backfill = inputs.get_is_earliest_backfill()
        data_interval_start, data_interval_end = get_data_interval(inputs.interval, inputs.data_interval_end)
        should_backfill_from_beginning = is_backfill and is_earliest_backfill

        start_batch_export_run_inputs = StartBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            backfill_id=inputs.backfill_details.backfill_id if inputs.backfill_details else None,
        )
        try:
            run_id = await workflow.execute_activity(
                start_batch_export_run,
                start_batch_export_run_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=0,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError", "OverBillingLimitError"],
                ),
            )
        except OverBillingLimitError:
            return

        insert_inputs = BigQueryInsertInputs(
            team_id=inputs.team_id,
            table_id=inputs.table_id,
            dataset_id=inputs.dataset_id,
            project_id=inputs.project_id,
            private_key=inputs.private_key,
            private_key_id=inputs.private_key_id,
            token_uri=inputs.token_uri,
            client_email=inputs.client_email,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            use_json_type=inputs.use_json_type,
            run_id=run_id,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
            # TODO: Remove after updating existing batch exports.
            batch_export_schema=inputs.batch_export_schema,
            batch_export_id=inputs.batch_export_id,
            destination_default_fields=bigquery_default_fields(),
        )

        await execute_batch_export_using_internal_stage(
            insert_into_bigquery_activity_from_stage,
            insert_inputs,
            interval=inputs.interval,
            maximum_retry_interval_seconds=240,
        )
