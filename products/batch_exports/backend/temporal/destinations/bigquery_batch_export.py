import io
import os
import json
import time
import typing
import asyncio
import datetime as dt
import contextlib
import dataclasses
import collections.abc

from django.conf import settings

import boto3
import pyarrow as pa
import requests
import google.auth
import google.auth.aws
import google.auth.exceptions
import google.auth.transport.requests
import google.auth.impersonated_credentials
from google.api_core.exceptions import (
    Forbidden,
    GatewayTimeout,
    GoogleAPICallError,
    InternalServerError,
    NotFound,
    PermissionDenied,
    ServiceUnavailable,
    TooManyRequests,
)
from google.cloud import bigquery, iam_admin_v1
from google.cloud.bigquery.table import RowIterator, _EmptyRowIterator
from google.oauth2 import service_account
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.models.integration import GoogleCloudServiceAccountIntegration, Integration
from posthog.models.team import Team
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.service import (
    BatchExportField,
    BatchExportInsertInputs,
    BatchExportModel,
    BatchExportSchema,
    BigQueryBatchExportInputs,
)
from products.batch_exports.backend.temporal.batch_exports import (
    OverBillingLimitError,
    StartBatchExportRunInputs,
    default_fields,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.pipeline.consumer import Consumer, run_consumer_from_stage
from products.batch_exports.backend.temporal.pipeline.entrypoint import execute_batch_export_using_internal_stage
from products.batch_exports.backend.temporal.pipeline.producer import Producer
from products.batch_exports.backend.temporal.pipeline.table import Field, Table, TableReference
from products.batch_exports.backend.temporal.pipeline.transformer import (
    ChunkTransformerProtocol,
    JSONLStreamTransformer,
    ParquetStreamTransformer,
    PipelineTransformer,
    SchemaTransformer,
)
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult, reduce_batch_export_results
from products.batch_exports.backend.temporal.spmc import (
    RecordBatchQueue,
    raise_on_task_failure,
    wait_for_schema_or_producer,
)
from products.batch_exports.backend.temporal.utils import JsonType, handle_non_retryable_errors

NON_RETRYABLE_ERROR_TYPES = (
    # Raised on missing permissions.
    "Forbidden",
    # Invalid token.
    "RefreshError",
    # Usually means the dataset or project_id doesn't exist.
    "NotFound",
    # Raised when something about dataset is wrong (not alphanumeric, too long, etc).
    "BadRequest",
    # Raised when table_id isn't valid. Sadly, `ValueError` is rather generic, but we
    # don't anticipate a `ValueError` thrown from our own export code.
    "ValueError",
    # Raised when attempting to run a batch export without required BigQuery permissions.
    # Our own version of `Forbidden`.
    "MissingRequiredPermissionsError",
    # Raised when a query takes too long to start (i.e. remains in "PENDING" state for too long).
    "StartQueryTimeoutError",
    # A service account we are supposed to impersonate does not exist.
    "ServiceAccountNotFoundError",
    # We could not verify that the service account we are meant to use belongs to the
    # organization this batch export is running for.
    "ServiceAccountOwnershipError",
    # Raised when the BigQuery integration is not found.
    "BigQueryIntegrationNotFoundError",
)

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger("EXTERNAL")

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


class BigQueryType(typing.NamedTuple):
    name: BigQueryTypeName
    repeated: bool


def bigquery_type_to_data_type(type: BigQueryType) -> pa.DataType:
    """Mapping of `BigQueryType` to corresponding `pa.DataType`."""
    match type.name:
        case "STRING":
            base_type: pa.DataType = pa.string()
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
        bq_type: BigQueryTypeName = "STRING"
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

    elif pa.types.is_list(data_type) and pa.types.is_string(data_type.value_type):  # type: ignore[attr-defined]
        bq_type = "STRING"
        repeated = True

    else:
        raise ValueError(f"Unsupported type '{data_type}'")

    return BigQueryType(name=bq_type, repeated=repeated)


class BigQueryField(Field):
    """A field of a BigQueryTable."""

    def __init__(self, name: str, type: BigQueryType, nullable: bool):
        self.name = name
        self.alias = name
        self.bigquery_type = type
        self.nullable = nullable
        self.data_type = bigquery_type_to_data_type(type)

    @classmethod
    def from_arrow_field(cls, field: pa.Field) -> typing.Self:
        type = data_type_to_bigquery_type(field.type)
        return cls(field.name, type, nullable=field.nullable)

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
        primary_key: collections.abc.Iterable[str],
        version_key: collections.abc.Iterable[str],
    ) -> typing.Self:
        self = cls.from_arrow_schema_with_field_type(
            schema,
            BigQueryField,
            table_id,
            (project_id, dataset_id),
            primary_key,
            version_key,
        )
        if "timestamp" in self:
            # TODO: Choosing which column and granularity to use as partitioning should be a configuration parameter.
            # 'timestamp' is used for backwards compatibility.
            self.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY, field="timestamp"
            )
        return self

    @property
    def project_id(self) -> str:
        return self.parents[0]

    @property
    def dataset_id(self) -> str:
        return self.parents[1]


class Boto3CredentialsSupplier(google.auth.aws.AwsSecurityCredentialsSupplier):
    """Implementation of credential supplier for `google.auth` using `boto3`.

    The default credential supplier provided by `google.auth` tries to manually execute
    requests, but it's more straight forward for us to rely on `boto3` to resolve
    credentials.

    The interface requires all methods to be blocking, but we assume credentials are
    lazily loaded, and only fetched within some method wrapped by `asyncio.to_thread`.

    Moreover, `boto3` claims to automatically refresh credentials, so we delegate to it
    for that.

    All methods in the interface require raising `google.auth.exceptions.RefreshError`
    indicating to the Google SDK whether the error can be retried or not, so we comply.
    """

    def __init__(self, session: boto3.Session | None = None) -> None:
        self.session = session or boto3.Session()

    def get_aws_security_credentials(self, context, request) -> google.auth.aws.AwsSecurityCredentials:
        """Return AWS credentials using boto3."""
        session_credentials = self.session.get_credentials()
        if session_credentials is None:
            raise google.auth.exceptions.RefreshError("Cannot obtain AWS credentials", retryable=False)

        credentials = session_credentials.get_frozen_credentials()

        if credentials.access_key is None:
            raise google.auth.exceptions.RefreshError("Cannot obtain AWS credentials", retryable=False)

        if credentials.secret_key is None:
            raise google.auth.exceptions.RefreshError("Cannot obtain AWS credentials", retryable=False)

        return google.auth.aws.AwsSecurityCredentials(
            credentials.access_key,
            credentials.secret_key,
            credentials.token,
        )

    def get_aws_region(self, context, request) -> str:
        """Similar to the default implementation, but without a fallback request."""
        env_aws_region = os.environ.get("AWS_REGION")
        if env_aws_region is not None:
            return env_aws_region

        env_aws_region = os.environ.get("AWS_DEFAULT_REGION")
        if env_aws_region is not None:
            return env_aws_region

        raise google.auth.exceptions.RefreshError("AWS region not populated", retryable=False)


class ServiceAccountNotFoundError(Exception):
    def __init__(self, email: str):
        super().__init__(f"Service account '{email}' was not found")


class ServiceAccountOwnershipError(Exception):
    def __init__(self, email: str, organization_id: str):
        super().__init__(
            f"Could not verify that service account '{email}' is owned by your organization. "
            f"Have you added 'posthog:{organization_id}' to your service account's description?"
        )


def get_our_google_cloud_credentials() -> google.auth.impersonated_credentials.Credentials:
    """Return our own Google Cloud credentials, using AWS authentication."""
    our_credentials = google.auth.impersonated_credentials.Credentials(
        source_credentials=google.auth.aws.Credentials(
            audience=settings.BATCH_EXPORT_BIGQUERY_STS_AUDIENCE_FIELD,
            subject_token_type="urn:ietf:params:aws:token-type:aws4_request",  # Only possible value
            token_url="https://sts.googleapis.com/v1/token",  # Default
            aws_security_credentials_supplier=Boto3CredentialsSupplier(),
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        ),
        target_principal=settings.BATCH_EXPORT_BIGQUERY_SERVICE_ACCOUNT,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        lifetime=3600,
    )
    return our_credentials


class GoogleCloudCredentialsError(Exception):
    """Raised when we cannot acquire PostHog Google Cloud credentials."""

    def __init__(self):
        super().__init__("Failed to acquire PostHog Google Cloud credentials")


async def ensure_our_google_cloud_credentials_are_valid():
    """Raise `InvalidCredentialsError` if we cannot refresh our credentials."""
    our_credentials = get_our_google_cloud_credentials()
    try:
        await asyncio.to_thread(our_credentials.refresh, google.auth.transport.requests.Request())
    except Exception as e:
        raise GoogleCloudCredentialsError from e


async def get_service_account_description(
    service_account_email: str,
) -> str:
    """Return the service account's description.

    Uses our credentials to authenticate.
    """
    our_credentials = get_our_google_cloud_credentials()
    client = iam_admin_v1.IAMAsyncClient(credentials=our_credentials)

    try:
        sa = await client.get_service_account(
            request=iam_admin_v1.GetServiceAccountRequest(name=f"projects/-/serviceAccounts/{service_account_email}")
        )
    except PermissionDenied:
        EXTERNAL_LOGGER.exception(
            "Failed to describe the service account '%s' to verify ownership. "
            "Have you granted 'iam.serviceAccounts.get' to the PostHog service account to operate on it?",
            service_account_email,
        )
        raise MissingRequiredPermissionsError()
    except NotFound:
        raise ServiceAccountNotFoundError(service_account_email)

    return sa.description


async def verify_impersonated_service_account_ownership(
    service_account_email: str,
    team_id: int,
    max_attempts: int = 3,
) -> None:
    """Verify the service account is owned by the organization `team_id` belongs to.

    We do this by checking if 'posthog:{organization_id}' is present in the service
    account's description, which we require users to do when signing up.

    This helps mitigate the confused deputy problem which can happen if a malicious
    organization were to sign up with another organization's service account.

    This verification only makes sense when impersonating a user's service account. If
    we are using credentials directly then it is reasonable to assume only the
    organization who owns the account could have generated said credentials. And if that
    turns out to not be the case, then said organization would have had their Google
    Cloud account breached and that's not something we can verify here.

    Finally, Google Cloud uses some form of eventual consistency for service account
    updates. This can mean that a service account description is updated but not fully
    propagated by the time we get here, so we retry a `max_attempts` times if the
    description does not match the first time.
    """
    if max_attempts <= 0:
        raise ValueError("`max_attempts` must be at least 1")

    team = await Team.objects.aget(id=team_id)
    organization_id = team.organization_id

    attempt = 0
    initial_interval = 3
    backoff_factor = 2

    while attempt < max_attempts:
        description = await get_service_account_description(service_account_email)

        if f"posthog:{organization_id}" in description:
            return

        await asyncio.sleep(initial_interval * (backoff_factor**attempt))
        attempt += 1

    raise ServiceAccountOwnershipError(service_account_email, str(organization_id))


def impersonate_service_account(
    integration: GoogleCloudServiceAccountIntegration,
) -> google.auth.impersonated_credentials.Credentials:
    """Impersonate a user's service account using our own.

    This requires that the user's service account grants our own service account the
    `roles/iam.serviceAccountTokenCreator` role on their service account.
    """
    service_account_email = integration.service_account_email
    our_credentials = get_our_google_cloud_credentials()

    their_credentials = google.auth.impersonated_credentials.Credentials(
        source_credentials=our_credentials,
        target_principal=service_account_email,
        target_scopes=["https://www.googleapis.com/auth/bigquery"],
        lifetime=3600,
    )

    return their_credentials


class BigQueryClient:
    """Async client to interact with BigQuery.

    Wraps a non-async `bigquery.Client` and exposes async versions of some of its
    methods.

    Interacting with BigQuery requires a service account with the necessary permissions.
    In order to authenticate with this service account, you should provide a
    `GoogleCloudServiceAccountIntegration` to `from_service_account_integration`. The
    `from_service_account_inputs` classmethod is maintained for backwards compatibility,
    but may be removed in the future.

    Authenticating with an integration supports two possible authentication mechanisms:
    * Impersonating the service account
    * Directly authenticating using the service account credentials

    The first method is preferred as it doesn't require any long-lived credentials to be
    exchanged or stored. It works by using AWS credentials available in production
    environments to authenticate to our own service account. If a user has then granted
    us the right permissions, we can use our own service account to impersonate theirs.

    The second method directly uses the user's service account's credentials, which must
    be stored somewhere, so it is not recommended.
    """

    def __init__(self, client: bigquery.Client):
        self.sync_client = client

        self.logger = LOGGER.bind(project_id=client.project)
        self.external_logger = EXTERNAL_LOGGER.bind(project_id=client.project)

    async def __aenter__(self) -> typing.Self:
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await asyncio.to_thread(self.sync_client.close)
        return None

    @classmethod
    def from_service_account_integration(
        cls,
        integration: GoogleCloudServiceAccountIntegration,
    ) -> typing.Self:
        """Initialize a client from a service account integration.

        The integration can contain the keys of the service account we are meant to use,
        in which case we just use it. If no keys are present, then we are meant to
        impersonate the service account using our own.
        """
        if not integration.has_key():
            their_credentials = impersonate_service_account(integration)
        else:
            their_credentials = service_account.Credentials.from_service_account_info(
                integration.service_account_info,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )

        client = bigquery.Client(
            project=integration.project_id,
            credentials=their_credentials,
        )
        return cls(client)

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

        if isinstance(table, BigQueryTable) and table.time_partitioning is not None:
            bq_table.time_partitioning = table.time_partitioning

        created_bq_table = await asyncio.to_thread(self.sync_client.create_table, bq_table, exists_ok=exists_ok)

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
        await asyncio.to_thread(self.sync_client.delete_table, table.fully_qualified_name, not_found_ok=not_found_ok)

        return None

    async def get_table(
        self,
        table: BigQueryTable | TableReference,
    ) -> BigQueryTable:
        """Get a table in BigQuery."""
        bq_table = await asyncio.to_thread(self.sync_client.get_table, table.fully_qualified_name)

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

    async def execute_query(
        self, query: str, start_query_timeout: float | int = 15 * 60, poll_interval: float | int = 0.5
    ) -> RowIterator | _EmptyRowIterator:
        """Execute a query and wait for it to complete.

        Args:
            query: The query to execute.
            start_query_timeout: The timeout (in seconds) to wait for the query to start.
            poll_interval: The interval (in seconds) to poll for job state changes (PENDING -> RUNNING).

        Returns:
            The query result.

        Raises:
            StartQueryTimeoutError: If the query took too long to start (i.e. remained in "PENDING" state for
                longer than the timeout duration).
        """
        job_config = bigquery.QueryJobConfig()
        query_start_time = time.monotonic()
        query_job = await asyncio.to_thread(self.sync_client.query, query, job_config=job_config)

        # if query is in "PENDING" state, wait for it to start (and timeout if it takes too long)
        if query_job.state == "PENDING":
            while True:
                await asyncio.to_thread(query_job.reload)
                if query_job.state != "PENDING":
                    break
                query_duration = time.monotonic() - query_start_time
                if query_duration > start_query_timeout:
                    query_id = query_job.query_id
                    error_msg = f"Query still in 'PENDING' state after {start_query_timeout} seconds; timing out."
                    if query_id is not None:
                        error_msg += f" Query ID: {query_id}"
                    self.external_logger.error(error_msg)
                    # best-effort attempt to cancel the query
                    try:
                        await asyncio.to_thread(query_job.cancel)
                    except (GoogleAPICallError, requests.exceptions.RequestException) as err:
                        self.external_logger.warning("Failed to cancel query when cleaning up: %s", err)
                    raise StartQueryTimeoutError(query_id, start_query_timeout)
                await asyncio.sleep(poll_interval)

        # wait for the query to complete and return the result
        return await asyncio.to_thread(query_job.result)

    async def check_for_query_permissions(
        self,
        table: BigQueryTable | TableReference,
    ) -> bool:
        """Attempt to SELECT from table to check for query permissions."""
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
            await self.execute_query(query)
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
            SAFE.PARSE_JSON(
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

        result = await self.execute_query(query)
        return result

    async def merge_into_final_from_stage(
        self,
        final: BigQueryTable,
        stage: BigQueryTable,
    ):
        """Merge two identical person model tables in BigQuery."""

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
                SAFE.PARSE_JSON(
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

        self.logger.info("Merging into final table", table_id=final.name, stage_table_id=stage.name)
        return await self.execute_query(merge_query)

    async def load_file(self, file, format: FileFormat, table: BigQueryTable):
        """Load a file into BigQuery table."""
        schema = tuple(field.to_destination_field() for field in table.fields)
        if format == "Parquet":
            opts = bigquery.format_options.ParquetOptions()
            opts.enable_list_inference = True

            job_config = bigquery.LoadJobConfig(
                source_format="PARQUET",
                parquet_options=opts,
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

        self.logger.info("Waiting for BigQuery load job", format=format, table_id=table.name)

        initial_retry = 1
        backoff_factor = 2
        max_retry = 32
        attempt = 0

        while True:
            try:
                result = await asyncio.to_thread(self._run_load_job, file, bq_table, job_config=job_config)
            except (
                TooManyRequests,
                ServiceUnavailable,
                GatewayTimeout,
                InternalServerError,
                BigQueryQuotaExceededError,
            ) as err:
                backoff = min(max_retry, initial_retry * (backoff_factor**attempt))
                self.logger.exception(
                    "LoadJob transient error encountered", attempt=attempt, backoff=backoff, error_code=err.code
                )
                self.external_logger.error(  # noqa: TRY400
                    "Encountered a service-side issue that will be retried in %d seconds, this is attempt number %d."
                    " These type of errors indicate BigQuery may be under too much load from all sources. You may have"
                    " to check with BigQuery if it keeps happening consistently."
                    " Error: %s",
                    backoff,
                    attempt,
                    err,
                    attempt=attempt,
                    backoff=backoff,
                    error_code=err.code,
                )

                await asyncio.sleep(backoff)
                attempt += 1

            else:
                return result

    def _run_load_job(self, file, bq_table, job_config):
        """Run a BigQuery LoadJob and return its result.

        This method blocks and should only be run on an executor.
        """
        try:
            load_job = self.sync_client.load_table_from_file(file, bq_table, job_config=job_config, rewind=True)
            result = load_job.result()
        except Forbidden as err:
            if err.reason == "quotaExceeded":
                self.external_logger.exception(
                    "BigQuery quota long-term limit exceeded. We will attempt to retry the batch export with an exponential back-off, but it may take several minutes or longer until the quota is restored."
                )
                raise BigQueryQuotaExceededError(err.message) from err

            raise
        else:
            return result


class MissingRequiredPermissionsError(Exception):
    """Raised when missing required permissions in BigQuery."""

    def __init__(self):
        super().__init__("Missing required permissions to run this batch export")


class BigQueryQuotaExceededError(Exception):
    """Exception raised when a BigQuery quota is exceeded.

    This error indicates that we have been exporting too much data and need to
    slow down. This error is retryable.
    """

    code = 403  # BigQuery reports quota errors as 403 Forbidden.

    def __init__(self, message: str):
        super().__init__(f"A BigQuery quota has been exceeded. Error: {message}")


class StartQueryTimeoutError(TimeoutError):
    """Exception raised when a query takes too long to start."""

    def __init__(self, query_id: str | None, timeout: float | int):
        error_msg = f"Query still in 'PENDING' state after {timeout} seconds; timing out."
        if query_id is not None:
            error_msg += f" Query ID: {query_id}"
        super().__init__(error_msg)


class BigQueryConsumer(Consumer):
    def __init__(
        self,
        client: BigQueryClient,
        table: BigQueryTable,
        file_format: FileFormat,
        model: str = "events",
    ):
        super().__init__(model=model)

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


async def run_consumers(
    client: BigQueryClient,
    table: BigQueryTable,
    file_format: FileFormat,
    producer_task: asyncio.Task[None],
    queue: RecordBatchQueue,
    can_perform_merge: bool,
    max_consumers: int,
    model: str = "events",
) -> BatchExportResult:
    tasks = []
    max_file_size_bytes_per_consumer = settings.BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES // max_consumers

    async with asyncio.TaskGroup() as tg:
        for _ in range(max_consumers):
            consumer = BigQueryConsumer(
                client=client,
                table=table,
                file_format=file_format,
                model=model,
            )

            if can_perform_merge:
                transformer: ChunkTransformerProtocol = PipelineTransformer(
                    transformers=(
                        SchemaTransformer(
                            table=table,
                        ),
                        ParquetStreamTransformer(
                            compression="zstd",
                            max_file_size_bytes=max_file_size_bytes_per_consumer,
                        ),
                    )
                )
            else:
                transformer = PipelineTransformer(
                    transformers=(
                        SchemaTransformer(
                            table=table,
                        ),
                        JSONLStreamTransformer(
                            max_file_size_bytes=max_file_size_bytes_per_consumer,
                        ),
                    )
                )

            tasks.append(
                tg.create_task(
                    consumer.start(
                        queue=queue,
                        producer_task=producer_task,
                        transformer=transformer,
                        json_columns=(),
                    )
                )
            )

    await raise_on_task_failure(producer_task)

    return reduce_batch_export_results(task.result() for task in tasks)


class MergeSettings(typing.NamedTuple):
    primary_key: collections.abc.Sequence[str]
    version_key: collections.abc.Sequence[str]


def _get_merge_settings(
    model: BatchExportModel | BatchExportSchema | None,
) -> MergeSettings | None:
    """Return merge settings for models that require merging."""
    if isinstance(model, BatchExportModel):
        if model.name == "persons":
            primary_key: collections.abc.Sequence[str] = ("team_id", "distinct_id")
            version_key: collections.abc.Sequence[str] = ("person_version", "person_distinct_id_version")
        elif model.name == "sessions":
            primary_key = ("team_id", "session_id")
            version_key = ("end_timestamp",)
        # TODO: Support merges in 'events'?
        else:
            return None
    else:
        return None

    return MergeSettings(primary_key, version_key)


@dataclasses.dataclass(kw_only=True)
class BigQueryInsertInputs(BatchExportInsertInputs):
    """Inputs for BigQuery."""

    dataset_id: str
    table_id: str
    project_id: str | None = None
    private_key: str | None = None
    private_key_id: str | None = None
    token_uri: str | None = None
    client_email: str | None = None
    use_json_type: bool = False
    integration_id: int | None = None


class BigQueryIntegrationNotFoundError(Exception):
    """Error raised when the BigQuery integration is not found."""

    pass


async def _get_google_cloud_service_account_integration(
    inputs: BigQueryInsertInputs,
) -> GoogleCloudServiceAccountIntegration | None:
    """Get the Google Cloud impersonated service account integration."""
    if inputs.integration_id is None:
        return None

    try:
        integration = await Integration.objects.aget(id=inputs.integration_id, team_id=inputs.team_id)
    except Integration.DoesNotExist:
        raise BigQueryIntegrationNotFoundError(
            f"Google Cloud service account integration with id '{inputs.integration_id}' not found"
        )
    return GoogleCloudServiceAccountIntegration(integration)


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_bigquery_activity_from_stage(inputs: BigQueryInsertInputs) -> BatchExportResult:
    """Activity streams data from ClickHouse to BigQuery."""
    google_cloud_integration = await _get_google_cloud_service_account_integration(inputs)
    if google_cloud_integration is not None:
        project_id = google_cloud_integration.project_id
    else:
        if inputs.project_id is None:
            # Mostly here for the type checkers
            # TODO: Remove this once everyone is on an integration
            raise ValueError("Missing required values")

        project_id = inputs.project_id

    bind_contextvars(
        team_id=inputs.team_id,
        destination="BigQuery",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        batch_export_id=inputs.batch_export_id,
        project_id=project_id,
        dataset_id=inputs.dataset_id,
        table_id=inputs.table_id,
        integration_id=inputs.integration_id,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    external_logger.info(
        "Batch exporting range %s - %s to BigQuery: %s.%s.%s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
        project_id,
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
            stage_folder=inputs.stage_folder,
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
            project_id=project_id,
            dataset_id=inputs.dataset_id,
            primary_key=merge_settings.primary_key if merge_settings else (),
            version_key=merge_settings.version_key if merge_settings else (),
        )

        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        attempt = activity.info().attempt
        stage_table_id = f"stage_{inputs.table_id}_{data_interval_end_str}_{inputs.team_id}_{attempt}"

        if google_cloud_integration is not None:
            if not google_cloud_integration.has_key():
                await verify_impersonated_service_account_ownership(
                    google_cloud_integration.service_account_email, inputs.team_id
                )
                await ensure_our_google_cloud_credentials_are_valid()
            bq_client = BigQueryClient.from_service_account_integration(google_cloud_integration)

        else:
            # TODO: Migrate everyone and remove this
            if (
                inputs.private_key is None
                or inputs.private_key_id is None
                or inputs.token_uri is None
                or inputs.client_email is None
            ):
                # If this ever happens then it's fine to fail.
                # Mostly here for the type checkers
                raise ValueError("Missing required values")
            bq_client = BigQueryClient.from_service_account_inputs(
                inputs.private_key, inputs.private_key_id, inputs.token_uri, inputs.client_email, project_id
            )

        async with bq_client:
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
                    # Do not partition the consumer table to avoid running into quota errors.
                    time_partitioning=None,
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
                file_format: typing.Literal["Parquet", "JSONLines"] = "Parquet" if can_perform_merge else "JSONLines"

                if str(inputs.team_id) not in settings.BATCH_EXPORT_BIGQUERY_USE_MULTIPLE_CONSUMERS_TEAM_IDS:
                    # This just repeats what's in `run_consumers` to preserve backwards compatibility
                    # while testing.
                    # TODO: Remove this or the else block after we have tested out whether multiple
                    # consumers are viable.
                    consumer = BigQueryConsumer(
                        client=bq_client,
                        table=bigquery_consumer_table,
                        file_format=file_format,
                        model=model.name if isinstance(model, BatchExportModel) else "events",
                    )

                    if can_perform_merge:
                        transformer: ChunkTransformerProtocol = PipelineTransformer(
                            transformers=(
                                SchemaTransformer(
                                    table=bigquery_consumer_table,
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
                                ),
                                JSONLStreamTransformer(
                                    max_file_size_bytes=settings.BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES,
                                ),
                            )
                        )

                    result = await run_consumer_from_stage(
                        queue=queue,
                        producer_task=producer_task,
                        consumer=consumer,
                        transformer=transformer,
                        json_columns=(),
                    )

                else:
                    result = await run_consumers(
                        client=bq_client,
                        table=bigquery_consumer_table,
                        file_format=file_format,
                        producer_task=producer_task,
                        queue=queue,
                        can_perform_merge=can_perform_merge,
                        max_consumers=settings.BATCH_EXPORT_BIGQUERY_MAX_CONSUMERS,
                        model=model.name if isinstance(model, BatchExportModel) else "events",
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
        data_interval_start, data_interval_end = get_data_interval(
            inputs.interval, inputs.data_interval_end, inputs.timezone
        )
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
            integration_id=inputs.integration_id,
        )

        await execute_batch_export_using_internal_stage(
            insert_into_bigquery_activity_from_stage,
            insert_inputs,
            interval=inputs.interval,
            maximum_retry_interval_seconds=240,
        )
