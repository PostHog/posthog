import io
import json
import time
import typing as t
import asyncio
import datetime as dt
import contextlib
import dataclasses
import collections.abc
from collections.abc import AsyncGenerator

from django.conf import settings

import pyarrow as pa
import urllib3.exceptions
from databricks import sql
from databricks.sdk._base_client import _BaseClient
from databricks.sdk.core import Config, ConfigAttribute, oauth_service_principal
from databricks.sdk.oauth import (
    OidcEndpoints,
    get_account_endpoints,
    get_azure_entra_id_workspace_endpoints,
    get_workspace_endpoints,
)
from databricks.sql.client import Connection
from databricks.sql.exc import DatabaseError, OperationalError, ServerOperationError
from databricks.sql.types import Row
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportInsertInputs,
    BatchExportModel,
    BatchExportSchema,
    DatabricksBatchExportInputs,
)
from posthog.models.integration import DatabricksIntegration, Integration
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.temporal.batch_exports import (
    StartBatchExportRunInputs,
    events_model_default_fields,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.pipeline.consumer import Consumer, run_consumer_from_stage
from products.batch_exports.backend.temporal.pipeline.entrypoint import execute_batch_export_using_internal_stage
from products.batch_exports.backend.temporal.pipeline.producer import Producer
from products.batch_exports.backend.temporal.pipeline.transformer import ParquetStreamTransformer, TransformerProtocol
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, wait_for_schema_or_producer
from products.batch_exports.backend.temporal.utils import (
    JsonType,
    cast_record_batch_schema_json_columns,
    handle_non_retryable_errors,
)

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger("EXTERNAL")


NON_RETRYABLE_ERROR_TYPES: list[str] = [
    # Our own exception when we can't connect to Databricks, usually due to invalid parameters.
    "DatabricksConnectionError",
    # Raised when we don't have sufficient permissions to perform an operation.
    "DatabricksInsufficientPermissionsError",
    # Raised when the Databricks integration is not found.
    "DatabricksIntegrationNotFoundError",
    # Raised when the Databricks integration is not valid.
    "DatabricksIntegrationError",
    # Raised when we hit our self-imposed long running operation timeout.
    # We don't want to continually retry as it could consume a lot of compute resources in the user's account.
    "DatabricksOperationTimeoutError",
]

DatabricksField = tuple[str, str]


class DatabricksConnectionError(Exception):
    """Error for Databricks connection."""

    pass


class DatabricksInsufficientPermissionsError(Exception):
    """Error for Databricks permission."""

    pass


class DatabricksIntegrationNotFoundError(Exception):
    """Error raised when the Databricks integration is not found."""

    pass


class DatabricksCatalogNotFoundError(Exception):
    """Error raised when the Databricks catalog is not found."""

    def __init__(self, catalog: str):
        super().__init__(f"Catalog '{catalog}' not found")


class DatabricksSchemaNotFoundError(Exception):
    """Error raised when the Databricks schema is not found."""

    def __init__(self, schema: str):
        super().__init__(f"Schema '{schema}' not found")


class DatabricksOperationTimeoutError(Exception):
    """Error raised when we hit our self-imposed long running operation timeout.

    We impose this timeout to prevent operations from running for too long, which could cause SLA violations and consume
    a lot of compute resources in the user's account.
    """

    def __init__(self, operation: str, timeout: float):
        super().__init__(
            f"{operation} timed out after {timeout} seconds. If this happens regularly, you may want to increase the size of your Databricks SQL warehouse."
        )


@dataclasses.dataclass(kw_only=True)
class DatabricksInsertInputs(BatchExportInsertInputs):
    """Inputs for Databricks.

    integration_id: the ID of the Databricks Integration model to use.
    http_path: HTTP Path value for user's all-purpose compute or SQL warehouse.
    catalog: the catalog to use for the export.
    schema: the schema to use for the export.
    table_name: the name of the table to use for the export.
    use_variant_type: whether to use the VARIANT data type for storing JSON data.
        If False, we will use the STRING data type. Using VARIANT for storing JSON data is recommended by Databricks,
        however, VARIANT is only available in Databricks Runtime 15.3 and above.
        See: https://docs.databricks.com/aws/en/semi-structured/variant
    use_automatic_schema_evolution: whether to use automatic schema evolution for the merge operation.
        If True, we will use `WITH SCHEMA EVOLUTION` to enable [automatic schema
        evolution](https://docs.databricks.com/aws/en/delta/update-schema#automatic-schema-evolution-for-delta-lake-merge).
        This means the target table will automatically be updated with the schema of the source table (however, no
        columns will be dropped from the target table).
        NOTE: currently we don't expose this in the frontend as we're assuming all users would want to use this.
    """

    integration_id: int
    http_path: str
    catalog: str
    schema: str
    table_name: str
    use_variant_type: bool = True
    use_automatic_schema_evolution: bool = True


class DatabricksConfig(Config):
    """Config for Databricks.

    We need to override the oidc_endpoints method to use a custom client with a custom timeout since the default
    implementation uses an unconfigurable timeout of 5 minutes. This means our code just hangs if the user provides
    invalid connection parameters.

    I have opened an issue with Databricks to make this timeout configurable:
    https://github.com/databricks/databricks-sdk-py/issues/1046

    Subclassing Config has a few issues however:

    The Databricks SDK's attributes() method has bugs with subclassing:
    1. It only looks at cls.__dict__, not inherited attributes
    2. It caches results in _attributes, which subclasses inherit

    We work around this by copying parent ConfigAttribute descriptors into our __dict__.
    """

    locals().update({k: v for k, v in Config.__dict__.items() if isinstance(v, ConfigAttribute)})

    @classmethod
    def attributes(cls):
        if "_attributes" not in cls.__dict__:
            try:
                delattr(cls, "_attributes")
            except AttributeError:
                pass
        return super().attributes()

    @property
    def oidc_endpoints(self) -> OidcEndpoints | None:
        self._fix_host_if_needed()
        if not self.host:
            return None
        if self.is_azure and self.azure_client_id:
            return get_azure_entra_id_workspace_endpoints(self.host)
        if self.is_account_client and self.account_id:
            return get_account_endpoints(self.host, self.account_id)
        return get_workspace_endpoints(self.host, client=_BaseClient(retry_timeout_seconds=5))


class DatabricksClient:
    # How often to poll for query status. This is a trade-off between responsiveness and number of
    # queries we make to Databricks. 1 second has been chosen rather arbitrarily.
    DEFAULT_POLL_INTERVAL = 1.0

    def __init__(
        self,
        server_hostname: str,
        http_path: str,
        client_id: str,
        client_secret: str,
        catalog: str,
        schema: str,
    ):
        self.server_hostname = server_hostname
        self.http_path = http_path
        self.client_id = client_id
        self.client_secret = client_secret
        self.catalog = catalog
        self.schema = schema

        self._connection: None | Connection = None

        self.logger = LOGGER.bind(server_hostname=server_hostname, http_path=http_path)
        self.external_logger = EXTERNAL_LOGGER.bind(server_hostname=server_hostname, http_path=http_path)

    @classmethod
    def from_inputs_and_integration(cls, inputs: DatabricksInsertInputs, integration: DatabricksIntegration) -> t.Self:
        """Initialize a DatabricksClient from `DatabricksInsertInputs` and `DatabricksIntegration`.

        The config for Databricks is divided between the inputs and the integration model:
        Anything that could be reused across batch exports is stored in the inputs, whereas anything that is specific to
        the Databricks instance we're connecting to is stored in the integration model.
        """
        return cls(
            server_hostname=integration.server_hostname,
            http_path=inputs.http_path,
            client_id=integration.client_id,
            client_secret=integration.client_secret,
            catalog=inputs.catalog,
            schema=inputs.schema,
        )

    @property
    def connection(self) -> Connection:
        """Raise if a `Connection` hasn't been established, else return it."""
        if self._connection is None:
            # this should never happen and inidicates a bug in our code (i.e. trying to execute a query before
            # establishing a connection)
            raise Exception("Not connected, open a connection by calling `connect`")
        return self._connection

    async def _connect(self):
        """Establish a raw Databricks connection in a separate thread."""

        def get_credential_provider():
            config = DatabricksConfig(
                host=f"https://{self.server_hostname}",
                client_id=self.client_id,
                client_secret=self.client_secret,
                auth_type="oauth-m2m",
                disable_async_token_refresh=True,
            )
            return oauth_service_principal(config)

        try:
            result = await asyncio.to_thread(
                sql.connect,
                server_hostname=self.server_hostname,
                http_path=self.http_path,
                credentials_provider=get_credential_provider,
                # user agent can be used for usage tracking
                user_agent_entry="PostHog batch exports",
                enable_telemetry=False,
                _socket_timeout=300,  # Databricks seems to use this for all timeouts
                _retry_stop_after_attempts_count=2,
                _retry_delay_max=1,
            )
        except TimeoutError:
            self.logger.info(
                "Timed out while trying to connect to Databricks. server_hostname: %s, http_path: %s",
                self.server_hostname,
                self.http_path,
            )
            raise DatabricksConnectionError(
                f"Timed out while trying to connect to Databricks. Please check that the server_hostname and http_path are valid."
            )
        # for some reason, Databricks reports some connection failures as a ValueError
        except (ValueError, urllib3.exceptions.HTTPError, urllib3.exceptions.MaxRetryError) as err:
            self.logger.info(
                "Failed to connect to Databricks: %s. server_hostname: %s, http_path: %s",
                err,
                self.server_hostname,
                self.http_path,
            )
            raise DatabricksConnectionError(
                "Failed to connect to Databricks. Please check that your connection details are valid."
            )
        except OperationalError as err:
            self.logger.info(
                "Failed to connect to Databricks: %s. server_hostname: %s, http_path: %s",
                err,
                self.server_hostname,
                self.http_path,
            )
            raise DatabricksConnectionError(f"Failed to connect to Databricks: {err}") from err

        return result

    @contextlib.asynccontextmanager
    async def connect(self, set_context: bool = True):
        """Manage a Databricks connection.

        Methods that require a connection should be ran within this block.

        If set_context is `True`, we call `use_catalog` and `use_schema` to ensure that all queries are run in the
        correct catalog and schema.
        """
        self.logger.info("Initializing Databricks connection")

        self._connection = await self._connect()
        self.logger.info("Connected to Databricks")

        if set_context is True:
            await self.use_catalog(self.catalog)
            await self.use_schema(self.schema)

        try:
            yield self
        finally:
            if self._connection:
                await asyncio.to_thread(self._connection.close)
            self._connection = None

    async def execute_query(
        self, query: str, parameters: dict | None = None, query_kwargs: dict | None = None, fetch_results: bool = True
    ) -> list[Row] | None:
        """Execute a query and wait for it to complete.

        We run the query in a separate thread to avoid blocking the event loop in the main thread.
        """
        query_kwargs = query_kwargs or {}
        query_start_time = time.time()
        self.logger.debug("Executing query: %s", query)

        with self.connection.cursor() as cursor:
            try:
                await asyncio.to_thread(cursor.execute, query, parameters, **query_kwargs)
            finally:
                query_execution_time = time.time() - query_start_time
                self.logger.debug("Query completed in %.2fs", query_execution_time)

            if not fetch_results:
                return None

            results = await asyncio.to_thread(cursor.fetchall)
            return results

    async def execute_async_query(
        self,
        query: str,
        parameters: dict | None = None,
        poll_interval: float | None = None,
        fetch_results: bool = True,
        timeout: float = 60 * 60,  # 1 hour
    ) -> list[Row] | None:
        """Execute a query asynchronously and poll for results.

        This is useful for long running queries as it means we don't need to maintain a network connection to the
        Databricks server, which could timeout or be interrupted.

        Executing the query and polling for results are done in separate threads in order to avoid blocking the event
        loop in the main thread.

        Args:
            query: The query to execute.
            parameters: The parameters to bind to the query.
            poll_interval: The interval (in seconds) to poll for results.
            fetch_results: Whether to fetch results.
            timeout: The timeout (in seconds) to wait for the query to complete.
                This is more of a safeguard than anything else, just to prevent us waiting forever.

        Returns:
            If `fetch_results` is `True`, the query results as a list of Row objects.
            Else when `fetch_results` is `False` we return `None`.
        """
        poll_interval = poll_interval or self.DEFAULT_POLL_INTERVAL

        query_start_time = time.time()
        self.logger.debug("Executing async query: %s", query)

        with self.connection.cursor() as cursor:
            await asyncio.to_thread(cursor.execute_async, query, parameters)

            self.logger.debug("Waiting for async query to complete")

            while await asyncio.to_thread(cursor.is_query_pending):
                await asyncio.sleep(poll_interval)
                if time.time() - query_start_time > timeout:
                    raise TimeoutError(f"Timed out waiting for query to complete after {timeout} seconds")

            # this should return an exception if the query failed so ensure we log the query time
            try:
                await asyncio.to_thread(cursor.get_async_execution_result)
            finally:
                query_execution_time = time.time() - query_start_time
                self.logger.debug("Async query completed in %.2fs", query_execution_time)

            if fetch_results is False:
                return None

            self.logger.debug("Fetching query results")
            results = await asyncio.to_thread(cursor.fetchall)
            self.logger.debug("Finished fetching query results")

            return results

    async def use_catalog(self, catalog: str):
        try:
            await self.execute_query(f"USE CATALOG `{catalog}`", fetch_results=False)
        except ServerOperationError as err:
            if err.message and "[NO_SUCH_CATALOG_EXCEPTION]" in err.message:
                raise DatabricksCatalogNotFoundError(catalog)
            raise

    async def use_schema(self, schema: str):
        try:
            await self.execute_query(f"USE SCHEMA `{schema}`", fetch_results=False)
        except ServerOperationError as err:
            if err.message and "[SCHEMA_NOT_FOUND]" in err.message:
                raise DatabricksSchemaNotFoundError(schema)
            raise

    @contextlib.asynccontextmanager
    async def managed_table(
        self,
        table_name: str,
        fields: list[DatabricksField],
        delete: bool = False,
    ):
        """Manage a table in Databricks by ensuring it exists while in context."""
        # log if we're creating a permanent table
        if delete is False:
            self.external_logger.info("Creating Databricks table %s", table_name)
        else:
            self.logger.info("Creating Databricks table %s", table_name)

        await self.acreate_table(table_name=table_name, fields=fields)

        yield table_name

        if delete is True:
            self.logger.info("Deleting Databricks table %s", table_name)
            await self.adelete_table(table_name)

    async def acreate_table(self, table_name: str, fields: list[DatabricksField]):
        """Asynchronously create the Databricks delta table if it doesn't exist."""
        field_ddl = ", ".join(f"`{field[0]}` {field[1]}" for field in fields)
        try:
            query = f"""
                CREATE TABLE IF NOT EXISTS `{table_name}` (
                    {field_ddl}
                )
                USING DELTA
                COMMENT 'PostHog generated table'
                """
            await self.execute_query(query, fetch_results=False)
        except ServerOperationError as err:
            if _is_insufficient_permissions_error(err):
                raise DatabricksInsufficientPermissionsError(f"Failed to create table: {err.message}")
            raise

    async def adelete_table(self, table_name: str):
        """Asynchronously delete the Databricks delta table if it exists."""
        try:
            await self.execute_query(f"DROP TABLE IF EXISTS `{table_name}`", fetch_results=False)
        except ServerOperationError as err:
            if _is_insufficient_permissions_error(err):
                raise DatabricksInsufficientPermissionsError(f"Failed to delete table: {err.message}")
            raise

    async def aput_file_stream_to_volume(self, file: io.BytesIO, volume_path: str, file_name: str):
        """Asynchronously put a local file stream to a Databricks volume."""
        await self.execute_query(
            f"PUT '__input_stream__' INTO '{volume_path}/{file_name}' OVERWRITE",
            query_kwargs={"input_stream": file},
        )

    async def acopy_into_table_from_volume(
        self,
        table_name: str,
        volume_path: str,
        fields: list[DatabricksField],
        with_schema_evolution: bool = True,
        timeout: float = 60 * 60,
    ) -> None:
        """Asynchronously copy data from a Databricks volume into a Databricks table."""
        self.logger.info("Copying data from volume into table '%s'", table_name)
        query = self._get_copy_into_table_from_volume_query(
            table_name=table_name, volume_path=volume_path, fields=fields, with_schema_evolution=with_schema_evolution
        )
        try:
            await self.execute_async_query(query, fetch_results=False, timeout=timeout)
        except TimeoutError:
            raise DatabricksOperationTimeoutError(operation="Copy into table from volume", timeout=timeout)
        except ServerOperationError as err:
            if _is_insufficient_permissions_error(err):
                raise DatabricksInsufficientPermissionsError(
                    f"Failed to copy data from volume into table: {err.message}"
                )
            raise

    def _get_copy_into_table_from_volume_query(
        self, table_name: str, volume_path: str, fields: list[DatabricksField], with_schema_evolution: bool = True
    ) -> str:
        """Get the query to copy data from a Databricks volume into a Databricks table.

        We use the following COPY_OPTIONS:
        - force=true to ensure we always load in data from the files in the volume even if they have already been loaded
            previously
        - mergeSchema: whether to merge the schema of the source table with the schema of the target table

        Databricks is very strict about the schema of the destination table matching the schema of the Parquet file.
        Therefore, we need to cast the data to the correct type, otherwise the request will fail.
        - If the field type is VARIANT, we need to parse the string as JSON
        - If the field type is BIGINT or INTEGER, we cast the data in the file to that type just in case it is an unsigned integer
        """
        select_fields = []
        for field in fields:
            if field[1] == "VARIANT":
                select_fields.append(f"PARSE_JSON(`{field[0]}`) as `{field[0]}`")
            elif field[1] == "BIGINT":
                select_fields.append(f"CAST(`{field[0]}` as BIGINT) as `{field[0]}`")
            elif field[1] == "INTEGER":
                select_fields.append(f"CAST(`{field[0]}` as INTEGER) as `{field[0]}`")
            else:
                select_fields.append(f"`{field[0]}`")
        select_fields_str = ", ".join(select_fields)

        merge_schema = f"true" if with_schema_evolution else "false"

        return f"""
        COPY INTO `{table_name}`
        FROM (
            SELECT {select_fields_str} FROM '{volume_path}'
        )
        FILEFORMAT = PARQUET
        COPY_OPTIONS ('force' = 'true', 'mergeSchema' = '{merge_schema}')
        """

    @contextlib.asynccontextmanager
    async def managed_volume(self, volume: str):
        """Manage a volume in Databricks by ensuring it exists while in context."""
        self.logger.info("Creating Databricks volume %s", volume)
        await self.acreate_volume(volume)
        yield volume
        self.logger.info("Deleting Databricks volume %s", volume)
        await self.adelete_volume(volume)

    async def acreate_volume(self, volume: str):
        """Asynchronously create a Databricks volume."""
        try:
            await self.execute_query(
                f"CREATE VOLUME IF NOT EXISTS `{volume}` COMMENT 'PostHog generated volume'",
                fetch_results=False,
            )
        except ServerOperationError as err:
            if _is_insufficient_permissions_error(err):
                raise DatabricksInsufficientPermissionsError(f"Failed to create volume: {err.message}")
            raise

    async def adelete_volume(self, volume: str):
        """Asynchronously delete a Databricks volume."""
        try:
            await self.execute_query(
                f"DROP VOLUME IF EXISTS `{volume}`",
                fetch_results=False,
            )
        except ServerOperationError as err:
            if _is_insufficient_permissions_error(err):
                raise DatabricksInsufficientPermissionsError(f"Failed to delete volume: {err.message}")
            raise

    async def aget_table_columns(self, table_name: str) -> list[str]:
        """Asynchronously get the columns of a Databricks table.

        The Databricks connector has dedicated methods for retrieving metadata.
        """
        with self.connection.cursor() as cursor:
            try:
                await asyncio.to_thread(cursor.columns, table_name=table_name)
                results = await asyncio.to_thread(cursor.fetchall)
                try:
                    column_names = [row.name for row in results]
                except AttributeError:
                    # depending on the table column mapping mode, this could also be returned via a different attribute
                    column_names = [row.COLUMN_NAME for row in results]
            except DatabaseError as err:
                if "Expected field named: DataAccessConfigID" in str(err):
                    raise DatabricksInsufficientPermissionsError(
                        f"Failed to get table columns: {err}. Please check that you have SELECT permissions on the table."
                    )
                raise
            return column_names

    async def amerge_tables(
        self,
        target_table: str,
        source_table: str,
        merge_key: collections.abc.Iterable[str],
        update_key: collections.abc.Iterable[str],
        source_table_fields: collections.abc.Iterable[DatabricksField],
        with_schema_evolution: bool = True,
        timeout: float = 60 * 60,
    ) -> None:
        """Merge data from source_table into target_table in Databricks.

        If `with_schema_evolution` is True, we will use `WITH SCHEMA EVOLUTION` to enable [automatic schema
        evolution](https://docs.databricks.com/aws/en/delta/update-schema#automatic-schema-evolution-for-delta-lake-merge).
        This means the target table will automatically be updated with the schema of the source table (however, no
        columns will be dropped from the target table).

        Otherwise, we use the more manual approach of getting the column names from the target table and then specifying
        the individual columns in the `MERGE` query to update the target table.
        """

        assert merge_key, "Merge key must be defined"
        assert update_key, "Update key must be defined"

        if with_schema_evolution is True:
            self.logger.info(
                "Merging source table '%s' into target table '%s' with schema evolution", source_table, target_table
            )
            merge_query = self._get_merge_query_with_schema_evolution(
                target_table=target_table,
                source_table=source_table,
                merge_key=merge_key,
                update_key=update_key,
            )
        else:
            assert source_table_fields, "source_table_fields must be defined"
            # first we need to get the column names from the target table
            target_table_field_names = await self.aget_table_columns(target_table)
            self.logger.info(
                "Merging source table '%s' into target table '%s' without schema evolution", source_table, target_table
            )
            merge_query = self._get_merge_query_without_schema_evolution(
                target_table=target_table,
                source_table=source_table,
                merge_key=merge_key,
                update_key=update_key,
                source_table_fields=source_table_fields,
                target_table_field_names=target_table_field_names,
            )

        try:
            await self.execute_async_query(merge_query, fetch_results=False, timeout=timeout)
        except TimeoutError:
            raise DatabricksOperationTimeoutError(operation="Merge into target table", timeout=timeout)

    def _get_merge_query_with_schema_evolution(
        self,
        target_table: str,
        source_table: str,
        merge_key: collections.abc.Iterable[str],
        update_key: collections.abc.Iterable[str],
    ) -> str:
        merge_condition = " AND ".join([f"target.`{field}` = source.`{field}`" for field in merge_key])
        update_condition = " OR ".join([f"target.`{field}` < source.`{field}`" for field in update_key])

        return f"""
        MERGE WITH SCHEMA EVOLUTION INTO `{target_table}` AS target
        USING `{source_table}` AS source
        ON {merge_condition}
        WHEN MATCHED AND ({update_condition}) THEN
            UPDATE SET *
        WHEN NOT MATCHED THEN
            INSERT *
        """

    def _get_merge_query_without_schema_evolution(
        self,
        target_table: str,
        source_table: str,
        merge_key: collections.abc.Iterable[str],
        update_key: collections.abc.Iterable[str],
        source_table_fields: collections.abc.Iterable[DatabricksField],
        target_table_field_names: list[str],
    ) -> str:
        merge_condition = " AND ".join([f"target.`{field}` = source.`{field}`" for field in merge_key])
        update_condition = " OR ".join([f"target.`{field}` < source.`{field}`" for field in update_key])
        update_clause = ", ".join(
            [
                f"target.`{field[0]}` = source.`{field[0]}`"
                for field in source_table_fields
                if field[0] in target_table_field_names
            ]
        )
        field_names = ", ".join(
            [f"`{field[0]}`" for field in source_table_fields if field[0] in target_table_field_names]
        )
        values = ", ".join(
            [f"source.`{field[0]}`" for field in source_table_fields if field[0] in target_table_field_names]
        )

        return f"""
        MERGE INTO `{target_table}` AS target
        USING `{source_table}` AS source
        ON {merge_condition}
        WHEN MATCHED AND ({update_condition}) THEN
            UPDATE SET
                {update_clause}
        WHEN NOT MATCHED THEN
            INSERT ({field_names})
            VALUES ({values})
        """


def databricks_default_fields() -> list[BatchExportField]:
    """Default fields for a Databricks batch export.

    NOTE: for Databricks, we are exporting a reduced set of fields compared to other destinations as we're not so
    concerned about supporting legacy fields for backwards compatibility.
    """
    batch_export_fields = events_model_default_fields()
    # add a metadata field for the ingested timestamp to aid with debugging
    # (this is not strictly the time the data is ingested into Databricks but rather the time we query it from ClickHouse)
    batch_export_fields.append({"expression": "NOW64()", "alias": "databricks_ingested_timestamp"})
    return batch_export_fields


def _get_databricks_field_type(pa_type: pa.DataType, is_variant: bool) -> str | None:
    """Get the Databricks type for a PyArrow field."""
    if pa.types.is_string(pa_type) or isinstance(pa_type, JsonType):
        if is_variant:
            return "VARIANT"
        else:
            return "STRING"

    elif pa.types.is_binary(pa_type):
        return "BINARY"

    elif pa.types.is_signed_integer(pa_type) or pa.types.is_unsigned_integer(pa_type):
        if pa.types.is_uint64(pa_type) or pa.types.is_int64(pa_type):
            return "BIGINT"
        else:
            return "INTEGER"

    elif pa.types.is_floating(pa_type):
        if pa.types.is_float64(pa_type):
            return "DOUBLE"
        else:
            return "FLOAT"

    elif pa.types.is_boolean(pa_type):
        return "BOOLEAN"

    elif pa.types.is_timestamp(pa_type):
        return "TIMESTAMP"

    elif pa.types.is_list(pa_type):
        assert isinstance(pa_type, pa.ListType)
        list_type = _get_databricks_field_type(pa_type.value_type, False)
        return f"ARRAY<{list_type}>"

    return None


def _get_databricks_fields_from_record_schema(
    record_schema: pa.Schema, known_variant_columns: list[str]
) -> list[DatabricksField]:
    """Maps a PyArrow schema to a list of Databricks fields.

    Arguments:
        record_schema: The schema of a PyArrow RecordBatch from which we'll attempt to
            derive Databricks-supported types.
        known_variant_columns: If a string type field is a known VARIANT column then use VARIANT
            as its Databricks type.
    """
    databricks_schema: list[DatabricksField] = []

    for name in record_schema.names:
        pa_field = record_schema.field(name)
        is_variant = pa_field.name in known_variant_columns
        databricks_type = _get_databricks_field_type(pa_field.type, is_variant)
        if databricks_type is None:
            raise TypeError(f"Unsupported type in field '{name}': '{databricks_type}'")
        databricks_schema.append((name, databricks_type))

    return databricks_schema


class TableSettings(t.NamedTuple):
    table_fields: list[DatabricksField]
    record_batch_schema: pa.Schema
    known_variant_columns: list[str]


def _get_databricks_table_settings(
    model: BatchExportModel | BatchExportSchema | None,
    record_batch_schema: pa.Schema,
    use_variant_type: bool,
) -> TableSettings:
    """Get the various table settings for this batch export.

    For the events model, we actually export a reduced set of fields compared to other destinations for a number of reasons:
    - we do not need to support legacy fields, such as `set` and `set_once`
    - some fields, such as `ip` and `site_url`, are also present in `properties` so we can ignore these for efficiency
    - `elements` is not particularly useful in its current form (it is in a custom serialized format)
    """
    # we don't export the _inserted_at field
    record_batch_schema = pa.schema(
        [field.with_nullable(True) for field in record_batch_schema if field.name != "_inserted_at"]
    )

    if use_variant_type is True:
        json_type = "VARIANT"
        known_variant_columns = ["properties", "person_properties"]
    else:
        json_type = "STRING"
        known_variant_columns = []

    if model is None or (isinstance(model, BatchExportModel) and model.name == "events"):
        table_fields = [
            ("uuid", "STRING"),
            ("event", "STRING"),
            ("properties", json_type),
            ("distinct_id", "STRING"),
            ("team_id", "BIGINT"),
            ("timestamp", "TIMESTAMP"),
            ("databricks_ingested_timestamp", "TIMESTAMP"),
        ]
    else:
        table_fields = _get_databricks_fields_from_record_schema(
            record_batch_schema,
            known_variant_columns=known_variant_columns,
        )

    return TableSettings(table_fields, record_batch_schema, known_variant_columns)


def _get_databricks_merge_config(
    model: BatchExportModel | BatchExportSchema | None,
) -> tuple[bool, list[str], list[str]]:
    requires_merge = False
    merge_key = []
    update_key = []
    if isinstance(model, BatchExportModel):
        if model.name == "persons":
            requires_merge = True
            merge_key = ["team_id", "distinct_id"]
            update_key = ["person_version", "person_distinct_id_version"]
        elif model.name == "sessions":
            requires_merge = True
            merge_key = ["team_id", "session_id"]
            update_key = ["end_timestamp"]
    return requires_merge, merge_key, update_key


async def _get_databricks_integration(inputs: DatabricksInsertInputs) -> DatabricksIntegration:
    """Get the Databricks integration.

    Raises:
        DatabricksIntegrationNotFoundError: If the Databricks integration is not found.
        DatabricksIntegrationError: If the Databricks integration is not valid.
    """
    try:
        integration = await Integration.objects.aget(id=inputs.integration_id, team_id=inputs.team_id)
    except Integration.DoesNotExist:
        raise DatabricksIntegrationNotFoundError(f"Databricks integration with id '{inputs.integration_id}' not found")
    return DatabricksIntegration(integration)


def _is_insufficient_permissions_error(err: ServerOperationError) -> bool:
    """Check if the error is an insufficient permissions error."""
    if err.message is None:
        return False
    return "INSUFFICIENT_PERMISSIONS" in err.message or "PERMISSION_DENIED" in err.message


def _get_long_running_query_timeout(data_interval_start: dt.datetime | None, data_interval_end: dt.datetime) -> float:
    """Get the timeout to use for long running queries.

    Operations like COPY INTO TABLE can take a long time to complete, especially if there is a lot of data and
    the warehouse being used is not very powerful. We don't want to allow these queries to run for too long, as they can
    cause SLA violations and can consume a lot of compute resources in the user's account.

    We can probably reduce this timeout a bit once the beta testing phase is complete.
    """
    min_timeout_seconds = 30 * 60  # 30 minutes
    max_timeout_seconds = 6 * 60 * 60  # 6 hours
    if data_interval_start is None:
        return max_timeout_seconds
    interval_seconds = (data_interval_end - data_interval_start).total_seconds()
    # we don't want to timeout to be too short (eg in case of 5 min batch exports)
    # we also multiply the interval by 2 for now while we are in beta testing
    timeout_seconds = max(min_timeout_seconds, interval_seconds * 2)
    # we don't want to timeout to be too long (eg in case of 1 day batch exports)
    return min(timeout_seconds, max_timeout_seconds)


class DatabricksConsumer(Consumer):
    """A consumer that uploads data to a Databricks managed volume."""

    def __init__(
        self,
        client: DatabricksClient,
        volume_path: str,
    ):
        super().__init__()

        self.client = client
        self.volume_path = volume_path

        self.logger.bind(
            volume=self.volume_path,
        )

        self.current_file_index = 0
        self.current_buffer = io.BytesIO()

    async def consume_chunk(self, data: bytes):
        """Consume a chunk of data by writing it to the current buffer."""
        self.current_buffer.write(data)
        await asyncio.sleep(0)

    async def finalize_file(self):
        """Finalize the current file and start a new one."""
        await self._upload_current_buffer()
        self._start_new_file()

    def _start_new_file(self):
        self.current_file_index += 1

    async def _upload_current_buffer(self):
        """Upload the current buffer to Databricks, then start a new one."""
        buffer_size = self.current_buffer.tell()
        if buffer_size == 0:
            return  # Nothing to upload

        self.logger.info(
            "Uploading file %d with %.2f MB to Databricks volume '%s'",
            self.current_file_index,
            buffer_size / 1024 / 1024,
            self.volume_path,
        )

        self.current_buffer.seek(0)

        await self.client.aput_file_stream_to_volume(
            file=self.current_buffer,
            volume_path=self.volume_path,
            file_name=f"{self.current_file_index}.parquet",
        )

        self.external_logger.info(
            "File %d with %.2f MB uploaded to Databricks volume '%s'",
            self.current_file_index,
            buffer_size / 1024 / 1024,
            self.volume_path,
        )
        self.current_buffer = io.BytesIO()

    async def finalize(self):
        """Finalize by uploading any remaining data."""
        await self._upload_current_buffer()


@contextlib.asynccontextmanager
async def manage_resources(
    client: DatabricksClient,
    volume_name: str,
    fields: list[DatabricksField],
    table_name: str,
    stage_table_name: str | None = None,
) -> AsyncGenerator[tuple[str, str, str | None], None]:
    """Manage resources in Databricks by ensuring they exist while in context."""
    async with client.managed_volume(volume_name) as volume:
        async with client.managed_table(table_name, fields, delete=False) as table:
            if stage_table_name is not None:
                async with client.managed_table(stage_table_name, fields, delete=True) as stage_table:
                    yield volume, table, stage_table
            else:
                yield volume, table, None


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_databricks_activity_from_stage(inputs: DatabricksInsertInputs) -> BatchExportResult:
    """Activity to batch export data from internal S3 stage to Databricks."""
    bind_contextvars(
        team_id=inputs.team_id,
        destination="Databricks",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        batch_export_id=inputs.batch_export_id,
        catalog=inputs.catalog,
        schema=inputs.schema,
        table_name=inputs.table_name,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    databricks_integration = await _get_databricks_integration(inputs)

    external_logger.info(
        "Batch exporting range %s - %s to Databricks: %s.%s.%s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
        inputs.catalog,
        inputs.schema,
        inputs.table_name,
    )

    async with Heartbeater():
        model: BatchExportModel | BatchExportSchema | None = None
        if inputs.batch_export_schema is None:
            model = inputs.batch_export_model
        else:
            model = inputs.batch_export_schema

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_DATABRICKS_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = Producer()
        assert inputs.batch_export_id is not None
        producer_task = await producer.start(
            queue=queue,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=inputs.data_interval_start,
            data_interval_end=inputs.data_interval_end,
            max_record_batch_size_bytes=1024 * 1024 * 10,  # 10MB
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.data_interval_start or "START",
                inputs.data_interval_end or "END",
            )

            return BatchExportResult(records_completed=0, bytes_exported=0)

        table_fields, record_batch_schema, known_variant_columns = _get_databricks_table_settings(
            model=model,
            record_batch_schema=record_batch_schema,
            use_variant_type=inputs.use_variant_type,
        )

        requires_merge, merge_key, update_key = _get_databricks_merge_config(model=model)

        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        # include attempt in the stage table & volume names to avoid collisions if multiple attempts are running at the
        # same time (ideally this should never happen but it has in the past)
        attempt = activity.info().attempt
        stage_table_name: str | None = (
            f"stage_{inputs.table_name}_{data_interval_end_str}_{inputs.team_id}_{attempt}" if requires_merge else None
        )
        volume_name = f"stage_{inputs.table_name}_{data_interval_end_str}_{inputs.team_id}_{attempt}"
        volume_path = f"/Volumes/{inputs.catalog}/{inputs.schema}/{volume_name}"

        long_running_query_timeout = _get_long_running_query_timeout(
            dt.datetime.fromisoformat(inputs.data_interval_start) if inputs.data_interval_start else None,
            dt.datetime.fromisoformat(inputs.data_interval_end),
        )

        async with DatabricksClient.from_inputs_and_integration(
            inputs, databricks_integration
        ).connect() as databricks_client:
            async with manage_resources(
                client=databricks_client,
                volume_name=volume_name,
                fields=table_fields,
                table_name=inputs.table_name,
                stage_table_name=stage_table_name,
            ):
                consumer = DatabricksConsumer(
                    client=databricks_client,
                    volume_path=volume_path,
                )

                transformer: TransformerProtocol = ParquetStreamTransformer(
                    schema=cast_record_batch_schema_json_columns(
                        record_batch_schema, json_columns=known_variant_columns
                    ),
                    compression="zstd",
                    include_inserted_at=False,
                )

                result = await run_consumer_from_stage(
                    queue=queue,
                    consumer=consumer,
                    producer_task=producer_task,
                    schema=record_batch_schema,
                    transformer=transformer,
                    max_file_size_bytes=settings.BATCH_EXPORT_DATABRICKS_UPLOAD_CHUNK_SIZE_BYTES,
                    json_columns=known_variant_columns,
                )

                # TODO - maybe move this into the consumer finalize method?
                # Copy all staged files to the table
                await databricks_client.acopy_into_table_from_volume(
                    table_name=stage_table_name if stage_table_name else inputs.table_name,
                    volume_path=volume_path,
                    fields=table_fields,
                    with_schema_evolution=inputs.use_automatic_schema_evolution,
                    timeout=long_running_query_timeout,
                )

                if requires_merge and stage_table_name is not None:
                    await databricks_client.amerge_tables(
                        target_table=inputs.table_name,
                        source_table=stage_table_name,
                        source_table_fields=table_fields,
                        merge_key=merge_key,
                        update_key=update_key,
                        with_schema_evolution=inputs.use_automatic_schema_evolution,
                        timeout=long_running_query_timeout,
                    )

                return result


@workflow.defn(name="databricks-export", failure_exception_types=[workflow.NondeterminismError])
class DatabricksBatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into Databricks.

    This Workflow is intended to be executed both manually and by a Temporal
    Schedule. When ran by a schedule, `data_interval_end` should be set to
    `None` so that we will fetch the end of the interval from the Temporal
    search attribute `TemporalScheduledStartTime`.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DatabricksBatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return DatabricksBatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: DatabricksBatchExportInputs):
        """Workflow implementation to export data to Databricks table."""
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

        # should never happen here but check just in case
        if inputs.integration_id is None:
            raise DatabricksIntegrationNotFoundError("Databricks integration ID not provided")

        insert_inputs = DatabricksInsertInputs(
            team_id=inputs.team_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            run_id=run_id,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
            batch_export_schema=inputs.batch_export_schema,
            batch_export_id=inputs.batch_export_id,
            destination_default_fields=databricks_default_fields(),
            integration_id=inputs.integration_id,
            http_path=inputs.http_path,
            catalog=inputs.catalog,
            schema=inputs.schema,
            table_name=inputs.table_name,
            use_variant_type=inputs.use_variant_type,
            use_automatic_schema_evolution=inputs.use_automatic_schema_evolution,
        )

        await execute_batch_export_using_internal_stage(
            insert_into_databricks_activity_from_stage,
            insert_inputs,
            interval=inputs.interval,
        )
