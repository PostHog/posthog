"""BigQuery driver for PostHog's data-warehouse import pipeline.

Everything BigQuery-specific — client lifecycle (service account auth,
optional custom region), schema / primary-key / clustering listing, the
dlt pipeline build (temp-table dance for incremental syncs and views) —
lives on `BigQueryImplementation`. The source-class `BigQuerySource` is
a thin PostHog-layer wrapper that just holds an instance and validates
credentials.
"""

from __future__ import annotations

import math
import typing
import contextlib
import collections
import collections.abc
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.conf import settings

import boto3
import pyarrow as pa
import structlog
from google.api_core.exceptions import BadRequest, Forbidden, NotFound
from google.auth import (
    aws as google_auth_aws,
    credentials as google_auth_credentials,
    exceptions as google_auth_exceptions,
    impersonated_credentials as google_auth_impersonated_credentials,
)
from google.auth.transport.requests import AuthorizedSession
from google.cloud import bigquery, bigquery_storage
from google.cloud.bigquery.job import QueryJobConfig
from google.cloud.bigquery_storage_v1.services.big_query_read.transports.grpc import BigQueryReadGrpcTransport
from google.oauth2 import service_account
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import GoogleCloudServiceAccountIntegration, Integration
from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.helpers import (
    incremental_type_to_initial_value,
    incremental_type_to_operator,
)
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_TABLE_SIZE_BYTES
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES
from posthog.temporal.data_imports.sources.common.grpc import make_tracked_channel
from posthog.temporal.data_imports.sources.common.http import DEFAULT_RETRY, TrackedHTTPAdapter
from posthog.temporal.data_imports.sources.common.sql import (
    ColumnTypeCategory,
    ValidatedRowFilter,
    compute_projected_columns,
    is_multi_value_operator,
)
from posthog.temporal.data_imports.sources.common.sql.identifiers import BacktickIdentifierQuoter
from posthog.temporal.data_imports.sources.common.sql.implementation import SQLSourceImplementation
from posthog.temporal.data_imports.sources.common.sql.incremental import IncrementalFieldFilter
from posthog.temporal.data_imports.sources.common.sql.projection import format_projected_select_clause
from posthog.temporal.data_imports.sources.generated_configs import BigQuerySourceConfig

from products.data_warehouse.backend.types import IncrementalFieldType, PartitionSettings

__all__ = [
    "BigQueryAuthInfo",
    "BIGQUERY_TOKEN_RESPONSE_ERROR",
    "BigQueryImplementation",
    "BigQueryTokenRefreshError",
    "bigquery_client",
    "bigquery_storage_read_client",
    "build_destination_table_prefix",
    "delete_all_temp_destination_tables",
    "delete_table",
    "filter_bigquery_incremental_fields",
    "resolve_bigquery_auth",
    "validate_bigquery_credentials",
]

# Host used both to build the Storage Read API gRPC channel and to label the
# tracked gRPC transport's logs/metrics.
BIGQUERY_STORAGE_HOST = "bigquerystorage.googleapis.com"
BIGQUERY_SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/cloud-platform"]

# Stable, source-specific marker for a failed service-account OAuth token refresh.
# Used both when raising below and when matching in `BigQuerySource.get_non_retryable_errors`,
# so it must stay free of volatile data (urls, ids, timestamps).
BIGQUERY_TOKEN_RESPONSE_ERROR = "BigQuery OAuth token endpoint returned an unexpected response"


class BigQueryTokenRefreshError(Exception):
    """Raised when the service-account OAuth token endpoint returns a non-JSON-object 200.

    google-auth's `jwt_grant` reads `response_data["access_token"]` while guarding only
    against `KeyError`. When the token endpoint replies 200 with a body that isn't a JSON
    object — an intercepting proxy, or a misconfigured `token_uri` in the service-account
    key file — `response_data` is a `str` and the lookup raises an opaque
    `TypeError: string indices must be integers` instead of a `RefreshError`. We re-raise it
    as this clear, non-retryable error so the sync stops hammering an endpoint that can't
    authenticate us, and the user gets an actionable message.
    """


def build_destination_table_prefix(schema_id: str | None) -> str:
    return f"__posthog_import_{schema_id.replace('-', '_') if schema_id else ''}"


def _normalize_identifier(value: str) -> str:
    """Trim whitespace from a user-supplied BigQuery identifier.

    Project and dataset IDs are pasted into the source form by hand, so a stray
    leading or trailing space slips in easily. BigQuery then rejects every
    request with an opaque `BadRequest: Invalid project ID ' ...'` /
    `Invalid dataset ID ' ...'` that no amount of retrying can fix. Trimming
    here keeps the sync working instead of failing on a copy-paste artifact.
    """
    return value.strip()


def _resolve_project_id(config: BigQuerySourceConfig) -> str:
    return _normalize_identifier(config.key_file.project_id)


def _resolve_dataset_id(config: BigQuerySourceConfig) -> str:
    return _normalize_identifier(config.dataset_id)


def _resolve_region(config: BigQuerySourceConfig) -> str | None:
    if (
        config.use_custom_region
        and config.use_custom_region.enabled
        and config.use_custom_region.region is not None
        and _normalize_identifier(config.use_custom_region.region) != ""
    ):
        return _normalize_identifier(config.use_custom_region.region)
    return None


def _resolve_dataset_project_id(config: BigQuerySourceConfig) -> str | None:
    if (
        config.dataset_project
        and config.dataset_project.enabled
        and config.dataset_project.dataset_project_id is not None
        and _normalize_identifier(config.dataset_project.dataset_project_id) != ""
    ):
        return _normalize_identifier(config.dataset_project.dataset_project_id)
    return None


@dataclass(frozen=True)
class BigQueryAuthInfo:
    project_id: str
    credentials: google_auth_credentials.Credentials


class Boto3CredentialsSupplier(google_auth_aws.AwsSecurityCredentialsSupplier):
    """Resolve AWS credentials for Google impersonated credentials using boto3."""

    def __init__(self, session: boto3.Session | None = None) -> None:
        self.session = session or boto3.Session()

    def get_aws_security_credentials(
        self, context: google_auth_aws.AwsSecurityCredentialsSupplierContext, request
    ) -> google_auth_aws.AwsSecurityCredentials:
        session_credentials = self.session.get_credentials()
        if session_credentials is None:
            raise google_auth_exceptions.RefreshError("Cannot obtain AWS credentials", retryable=False)

        credentials = session_credentials.get_frozen_credentials()

        if credentials.access_key is None:
            raise google_auth_exceptions.RefreshError("Cannot obtain AWS credentials", retryable=False)

        if credentials.secret_key is None:
            raise google_auth_exceptions.RefreshError("Cannot obtain AWS credentials", retryable=False)

        return google_auth_aws.AwsSecurityCredentials(credentials.access_key, credentials.secret_key, credentials.token)

    def get_aws_region(self, context: google_auth_aws.AwsSecurityCredentialsSupplierContext, request) -> str:
        region_name = self.session.region_name
        if not region_name:
            raise google_auth_exceptions.RefreshError("AWS region not populated", retryable=False)
        return region_name


def _get_posthog_google_cloud_credentials() -> google_auth_impersonated_credentials.Credentials:
    sts_audience = getattr(settings, "BATCH_EXPORT_BIGQUERY_STS_AUDIENCE_FIELD", None)
    target_principal = getattr(settings, "BATCH_EXPORT_BIGQUERY_SERVICE_ACCOUNT", None)
    if not isinstance(sts_audience, str) or not sts_audience:
        raise ValueError("Google Cloud impersonation is not configured on this instance")
    if not isinstance(target_principal, str) or not target_principal:
        raise ValueError("Google Cloud impersonation is not configured on this instance")

    return google_auth_impersonated_credentials.Credentials(
        source_credentials=google_auth_aws.Credentials(
            audience=sts_audience,
            subject_token_type="urn:ietf:params:aws:token-type:aws4_request",
            token_url="https://sts.googleapis.com/v1/token",
            aws_security_credentials_supplier=Boto3CredentialsSupplier(),
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        ),
        target_principal=target_principal,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        lifetime=3600,
    )


def _resolve_auth_from_integration(integration_id: int, team_id: int) -> BigQueryAuthInfo:
    integration = Integration.objects.filter(id=integration_id, team_id=team_id).first()
    if integration is None:
        raise ValueError(f"Google Cloud service account integration with id '{integration_id}' not found")
    if integration.kind != Integration.IntegrationKind.GOOGLE_CLOUD_SERVICE_ACCOUNT:
        raise ValueError("Integration is not a Google Cloud service account integration")

    gcp_integration = GoogleCloudServiceAccountIntegration(integration)
    if gcp_integration.has_key():
        credentials = service_account.Credentials.from_service_account_info(
            gcp_integration.service_account_info, scopes=BIGQUERY_SCOPES
        )
    else:
        credentials = google_auth_impersonated_credentials.Credentials(
            source_credentials=_get_posthog_google_cloud_credentials(),
            target_principal=gcp_integration.service_account_email,
            target_scopes=BIGQUERY_SCOPES,
            lifetime=3600,
        )

    return BigQueryAuthInfo(project_id=gcp_integration.project_id, credentials=credentials)


def _resolve_auth_from_key_file(config: BigQuerySourceConfig) -> BigQueryAuthInfo:
    if config.key_file is None:
        raise ValueError("Missing BigQuery key_file configuration")

    project_id = config.key_file.project_id
    private_key = config.key_file.private_key
    private_key_id = config.key_file.private_key_id
    client_email = config.key_file.client_email
    token_uri = config.key_file.token_uri
    if not project_id or not private_key or not private_key_id or not client_email or not token_uri:
        raise ValueError("Missing required fields in BigQuery key_file configuration")
    credentials = service_account.Credentials.from_service_account_info(
        {
            "private_key": private_key,
            "private_key_id": private_key_id,
            "token_uri": token_uri,
            "client_email": client_email,
            "project_id": project_id,
        },
        scopes=BIGQUERY_SCOPES,
    )
    return BigQueryAuthInfo(project_id=project_id, credentials=credentials)

def _resolve_query_project(config: BigQuerySourceConfig) -> str:
    """Project used to run INFORMATION_SCHEMA discovery queries.

    Prefers the (optional) dataset project over the service account project,
    mirroring the routing the rest of the source uses.
    """
    dataset_project_id = _resolve_dataset_project_id(config)
    return dataset_project_id if dataset_project_id is not None else _resolve_project_id(config)


def resolve_bigquery_auth(config: BigQuerySourceConfig, team_id: int) -> BigQueryAuthInfo:
    if config.google_cloud_service_account_integration_id is not None:
        return _resolve_auth_from_integration(int(config.google_cloud_service_account_integration_id), team_id)
    return _resolve_auth_from_key_file(config)


@contextlib.contextmanager
def bigquery_client(
    project_id: str,
    location: str | None,
    credentials: google_auth_credentials.Credentials,
) -> typing.Iterator[bigquery.Client]:
    """Manage a BigQuery client."""
    project_id = _normalize_identifier(project_id)
    # AuthorizedSession is a `requests.Session` subclass that injects the OAuth2
    # bearer token. Mount our TrackedHTTPAdapter on it so every BigQuery REST
    # call is logged and metered alongside the other warehouse sources.
    authed_session = AuthorizedSession(credentials)
    tracked_adapter = TrackedHTTPAdapter(max_retries=DEFAULT_RETRY)
    authed_session.mount("https://", tracked_adapter)
    authed_session.mount("http://", tracked_adapter)
    client = bigquery.Client(
        project=project_id,
        location=location,
        credentials=credentials,
        _http=authed_session,
    )

    try:
        yield client
    finally:
        client.close()


@contextlib.contextmanager
def bigquery_storage_read_client(credentials: google_auth_credentials.Credentials):
    """Manage a BigQuery Storage client."""
    # The credentials are now passed as an argument to bigquery_client,
    # so the service_account.Credentials.from_service_account_info block is no longer needed here.
    # Build the credential-bearing gRPC channel ourselves, wrap it in the tracked
    # interceptors, then hand it to the transport. Passing a `channel` makes the
    # transport ignore credentials, so they must already be baked into the channel
    # via `create_channel(credentials=...)`. This routes the Storage Read API's
    # create_read_session (unary) + read_rows (server-streaming) RPCs through our
    # logging / metrics / sample-capture pipeline.
    #
    # `read_rows` streams Arrow record batches whose ReadRowsResponse messages
    # routinely exceed gRPC's default 4 MiB client receive limit (wide rows or large
    # string columns such as GeoJSON push a single message past it). When the
    # transport builds its own channel it sets both message-length limits to -1
    # (unlimited); because we supply the channel ourselves that default is skipped,
    # so we must replicate it here. Without it large pages fail with RESOURCE_EXHAUSTED
    # "Received message larger than max" and the sync can never make progress.
    channel = BigQueryReadGrpcTransport.create_channel(
        host=BIGQUERY_STORAGE_HOST,
        credentials=credentials,
        options=[
            ("grpc.max_send_message_length", -1),
            ("grpc.max_receive_message_length", -1),
        ],
    )
    tracked_channel = make_tracked_channel(channel, host=BIGQUERY_STORAGE_HOST)
    transport = BigQueryReadGrpcTransport(channel=tracked_channel)

    try:
        client = bigquery_storage.BigQueryReadClient(transport=transport)
        yield client
    finally:
        # We own the channel (built above), so we must close it — otherwise each
        # sync leaks an open gRPC channel + its file descriptors. Closing the
        # transport closes the underlying channel.
        transport.close()


def delete_table(
    table_id: str,
    project_id: str,
    location: str | None,
    credentials: google_auth_credentials.Credentials,
) -> None:
    with bigquery_client(project_id, location, credentials) as bq:
        bq.delete_table(table_id, not_found_ok=True)


def delete_all_temp_destination_tables(
    dataset_id: str,
    table_prefix: str,
    project_id: str,
    location: str | None,
    dataset_project_id: str | None,
    credentials: google_auth_credentials.Credentials,
    logger: None | FilteringBoundLogger,
) -> None:
    with bigquery_client(project_id, location, credentials) as bq:
        try:
            tables = bq.list_tables(bq.dataset(dataset_id, project=dataset_project_id or project_id))
            for table in tables:
                if table.table_id.startswith(table_prefix):
                    bq.delete_table(table.reference)
                    if logger:
                        logger.debug(f"Deleted bigquery table {table.table_id}")
        except (Forbidden, NotFound) as e:
            # Best-effort cleanup. If the service account has lost permission to list/delete
            # tables, or the dataset no longer exists, there's nothing to recover here — log
            # quietly rather than capturing an expected, non-actionable condition that would
            # otherwise fire on every sync for an affected source.
            if logger:
                logger.warning(f"Skipping temp table cleanup for dataset {dataset_id}: {e}")
        except Exception as e:
            capture_exception(e)


def filter_bigquery_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, type, nullable in columns:
        type = type.upper()
        if type.startswith("TIMESTAMP"):
            results.append((column_name, IncrementalFieldType.Timestamp, nullable))
        elif type.startswith("DATETIME"):
            results.append((column_name, IncrementalFieldType.DateTime, nullable))
        elif type.startswith("DATE"):
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif (
            type.startswith("INT64")
            or type.startswith("NUMERIC")
            or type.startswith("BIGNUMERIC")
            or type.startswith("INT")
            or type.startswith("SMALLINT")
            or type.startswith("INTEGER")
            or type.startswith("BIGINT")
            or type.startswith("TINYINT")
            or type.startswith("BYTEINT")
        ):
            results.append((column_name, IncrementalFieldType.Integer, nullable))

    return results


def validate_bigquery_credentials(
    dataset_id: str,
    project_id: str,
    credentials: google_auth_credentials.Credentials,
    dataset_project_id: str | None,
    location: str | None,
) -> tuple[bool, str | None]:
    # Apply normalizations from incoming branch for relevant identifiers
    dataset_id = _normalize_identifier(dataset_id)
    dataset_project_id = _normalize_identifier(dataset_project_id) if dataset_project_id else dataset_project_id
    location = _normalize_identifier(location) if location else location

    resolved_dataset_project_id = dataset_project_id or project_id
    with bigquery_client(project_id, location, credentials) as bq:
        try:
            bq.list_tables(
                bq.dataset(dataset_id, project=resolved_dataset_project_id),
                retry=bigquery.DEFAULT_RETRY.with_timeout(5),
            )
            return True, None
        except NotFound:
            return False, (f"BigQuery dataset '{dataset_id}' was not found in project '{resolved_dataset_project_id}'.")
        except Forbidden:
            return False, (
                f"Permission denied while accessing BigQuery dataset '{dataset_id}' in project "
                f"'{resolved_dataset_project_id}'."
            )
        except google_auth_exceptions.RefreshError as e:
            return False, f"Failed to obtain Google Cloud credentials: {e}"
        except Exception as e:
            capture_exception(e)
            return False, "Failed to validate BigQuery credentials"


def _get_partition_settings(
    table: bigquery.Table,
    client: bigquery.Client,
    partition_size_bytes: int = DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
) -> PartitionSettings | None:
    """Get partition settings for given BigQuery table.

    The `bigquery.Table` is refreshed to obtain latest number of rows and number
    of bytes. This will fail if the table doesn't exist.
    """
    table = client.get_table(table)

    if not table.num_rows or not table.num_bytes:
        return None

    avg_row_size = table.num_bytes / table.num_rows

    # Partition must have at least one row
    partition_size = max(round(partition_size_bytes / avg_row_size), 1)
    partition_count = math.floor(table.num_rows / partition_size)

    if partition_count == 0:
        return PartitionSettings(partition_count=1, partition_size=partition_size)

    return PartitionSettings(partition_count=partition_count, partition_size=partition_size)


def _get_primary_keys_for_table(table: bigquery.Table, client: bigquery.Client) -> list[str] | None:
    """Attempt to fetch primary keys for a BigQuery table.

    We will also attempt to look at table constraints to find primary keys.
    Otherwise, try to default to "id".
    """
    existing_fields = {field.name for field in table.schema}

    query = f"""
    SELECT kcu.column_name
    FROM `{table.dataset_id}`.INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
    JOIN `{table.dataset_id}`.INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
    ON tc.constraint_name = kcu.constraint_name
    WHERE tc.table_name = '{table.table_id}'
    AND tc.constraint_type = 'PRIMARY KEY'
    """

    job_config = QueryJobConfig()
    job = client.query(query, job_config=job_config, project=table.project)

    primary_keys = []
    for row in job.result():
        field_name = row["column_name"].removeprefix(f"{table.table_id}.")

        if field_name not in existing_fields:
            return None

        primary_keys.append(field_name)

    if not primary_keys:
        if "id" in existing_fields:
            return ["id"]
        return None
    return primary_keys


def _is_bigquery_resource_exceeded(error: BadRequest) -> bool:
    """True for BigQuery's `resourcesExceeded` query failures.

    BigQuery raises this when a query can't run within a node's memory (for
    example a large GROUP BY or sort over a big table). It's a property of the
    customer's data volume, not something we can fix, so best-effort diagnostic
    queries should degrade gracefully instead of treating it as an actionable
    crash.
    """
    reasons = {err.get("reason") for err in (getattr(error, "errors", None) or [])}
    return "resourcesExceeded" in reasons or "Resources exceeded during query execution" in str(error)


def _has_duplicate_primary_keys(table: bigquery.Table, client: bigquery.Client, primary_keys: list[str] | None) -> bool:
    if not primary_keys or len(primary_keys) == 0:
        return False

    try:
        query = f"""
            SELECT {", ".join(primary_keys)}
            FROM `{table.dataset_id}`.`{table.table_id}`
            GROUP BY {", ".join(primary_keys)}
            HAVING COUNT(*) > 1
        """

        job_config = QueryJobConfig()
        job = client.query(query, job_config=job_config, project=table.project)

        for _ in job.result():
            return True
    except BadRequest as e:
        if _is_bigquery_resource_exceeded(e):
            # The duplicate-key probe runs a full GROUP BY over the table; on very large
            # tables BigQuery can't sort it within a node's memory and raises
            # `resourcesExceeded`. That's a data-volume limit we can't fix, and this check
            # is best-effort, so skip it quietly rather than capturing non-actionable noise
            # on every sync.
            structlog.get_logger().warning(
                "Skipping duplicate primary key check for BigQuery table %s.%s: query exceeded BigQuery memory limits",
                table.dataset_id,
                table.table_id,
            )
            return False
        capture_exception(e)
    except Exception as e:
        capture_exception(e)

    return False


def _get_rows_to_sync(
    table: bigquery.Table,
    client: bigquery.Client,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: typing.Any,
    logger: FilteringBoundLogger,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
    row_filters: list[ValidatedRowFilter] | None = None,
) -> int:
    try:
        # `num_rows` is the whole-table count, so it's only a valid shortcut when nothing
        # filters the rows — row filters (like incremental) require an actual COUNT query.
        if not should_use_incremental_field and not row_filters:
            table = client.get_table(table)
            if table.num_rows:
                logger.debug(f"_get_rows_to_sync: table.num_rows={table.num_rows}")

                return table.num_rows

        inner_query, query_parameters = _get_query(
            should_use_incremental_field,
            db_incremental_field_last_value,
            table,
            incremental_field,
            incremental_field_type,
            row_filters=row_filters,
        )

        query = f"SELECT COUNT(*) FROM ({inner_query}) as t"

        job_config = QueryJobConfig(query_parameters=query_parameters)
        job = client.query(query, job_config=job_config, project=table.project)

        rows = job.result(page_size=1)
        row = next(rows, None)

        if row and len(row) > 0 and row[0] is not None:
            rows_to_sync_int = int(row[0])
            logger.debug(f"_get_rows_to_sync: rows_to_sync_int={rows_to_sync_int}")
            return rows_to_sync_int

        logger.debug("_get_rows_to_sync: No results returned. Using 0 as rows to sync")

        return 0
    except Exception as e:
        logger.debug(f"_get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
        capture_exception(e)

        return 0


_BQ_QUOTER = BacktickIdentifierQuoter()


def _bq_select_clause(
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None,
    incremental_field: str | None,
) -> str:
    """BigQuery SELECT-list with backtick quoting and identifier allowlist."""
    projected = compute_projected_columns(enabled_columns, primary_keys, incremental_field)
    return format_projected_select_clause(projected, _BQ_QUOTER)


# Map a column type category onto a BigQuery scalar-parameter type, used as a fallback
# when the column isn't found in the table schema.
_BQ_PARAM_TYPE_BY_CATEGORY = {
    ColumnTypeCategory.INTEGER: "INT64",
    ColumnTypeCategory.NUMERIC: "NUMERIC",
    ColumnTypeCategory.STRING: "STRING",
    ColumnTypeCategory.BOOLEAN: "BOOL",
    ColumnTypeCategory.DATE: "DATE",
    ColumnTypeCategory.TIMESTAMP: "TIMESTAMP",
}

_BQ_FIELD_TYPE_NORMALIZATION = {
    "INTEGER": "INT64",
    "INT64": "INT64",
    "FLOAT": "FLOAT64",
    "FLOAT64": "FLOAT64",
    "NUMERIC": "NUMERIC",
    "BIGNUMERIC": "BIGNUMERIC",
    "BOOLEAN": "BOOL",
    "BOOL": "BOOL",
    "STRING": "STRING",
    "DATE": "DATE",
    "DATETIME": "DATETIME",
    "TIMESTAMP": "TIMESTAMP",
    "TIME": "TIME",
}


def _adapt_bq_value(value: typing.Any, bq_type: str) -> typing.Any:
    """Coerce a coerced filter value to what the BigQuery client expects for `bq_type`."""
    if bq_type == "FLOAT64" and isinstance(value, Decimal):
        return float(value)
    if bq_type == "DATETIME" and isinstance(value, datetime) and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def _bq_row_filter_conditions(
    row_filters: list[ValidatedRowFilter] | None,
    bq_table: bigquery.Table,
) -> tuple[list[str], list[bigquery.ScalarQueryParameter]]:
    """Build row-filter SQL conditions + bound BigQuery scalar parameters.

    Columns are quoted; values leave only as named params (`@row_filter_i`, or
    `@row_filter_i_j` per element for IN). The param type follows the column's actual
    BigQuery type so DATETIME vs TIMESTAMP don't mismatch.
    """
    if not row_filters:
        return [], []

    column_field_types = {field.name: field.field_type for field in bq_table.schema}
    conditions: list[str] = []
    parameters: list[bigquery.ScalarQueryParameter] = []
    for index, row_filter in enumerate(row_filters):
        quoted = _BQ_QUOTER.quote(row_filter.column)
        bq_type = _BQ_FIELD_TYPE_NORMALIZATION.get(
            column_field_types.get(row_filter.column, "").upper()
        ) or _BQ_PARAM_TYPE_BY_CATEGORY.get(row_filter.category, "STRING")

        if is_multi_value_operator(row_filter.operator):
            placeholders = []
            for position, element in enumerate(row_filter.value):
                name = f"row_filter_{index}_{position}"
                placeholders.append(f"@{name}")
                parameters.append(bigquery.ScalarQueryParameter(name, bq_type, _adapt_bq_value(element, bq_type)))
            conditions.append(f"{quoted} {row_filter.operator} ({', '.join(placeholders)})")
        else:
            name = f"row_filter_{index}"
            conditions.append(f"{quoted} {row_filter.operator} @{name}")
            parameters.append(bigquery.ScalarQueryParameter(name, bq_type, _adapt_bq_value(row_filter.value, bq_type)))
    return conditions, parameters


def _get_query(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: typing.Any,
    bq_table: bigquery.Table,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
    enabled_columns: list[str] | None = None,
    primary_keys: list[str] | None = None,
    row_filters: list[ValidatedRowFilter] | None = None,
) -> tuple[str, list[bigquery.ScalarQueryParameter]]:
    select_clause = _bq_select_clause(enabled_columns, primary_keys, incremental_field)
    table_ref = f"`{bq_table.dataset_id}`.`{bq_table.table_id}`"
    filter_conditions, query_parameters = _bq_row_filter_conditions(row_filters, bq_table)

    if should_use_incremental_field:
        if incremental_field is None or incremental_field_type is None:
            raise ValueError("incremental_field and incremental_field_type can't be None")

        if db_incremental_field_last_value is None:
            last_value: int | datetime | date | str = incremental_type_to_initial_value(incremental_field_type)
        else:
            last_value = db_incremental_field_last_value

        if isinstance(last_value, datetime):
            # BigQuery DATETIME columns are timezone-naive and reject a literal that carries
            # a UTC offset (e.g. `1970-01-01T00:00:00+00:00`), failing with "Could not cast
            # literal ... to type DATETIME". The shared initial cursor value is tz-aware UTC,
            # so drop the offset for DATETIME fields. TIMESTAMP columns are timezone-aware and
            # keep it.
            if incremental_field_type == IncrementalFieldType.DateTime and last_value.tzinfo is not None:
                last_value = last_value.replace(tzinfo=None)
            last_value = f"'{last_value.isoformat()}'"
        elif isinstance(last_value, date):
            last_value = f"'{last_value.isoformat()}'"

        operator = incremental_type_to_operator(incremental_field_type)
        conditions = [f"`{incremental_field}` {operator} {last_value}", *filter_conditions]
        query = (
            f"SELECT {select_clause} FROM {table_ref} "
            f"WHERE {' AND '.join(conditions)} "
            f"ORDER BY `{incremental_field}` ASC"
        )
        return query, query_parameters

    if filter_conditions:
        return f"SELECT {select_clause} FROM {table_ref} WHERE {' AND '.join(filter_conditions)}", query_parameters

    return f"SELECT {select_clause} FROM {table_ref}", query_parameters


class BigQueryImplementation(SQLSourceImplementation[BigQuerySourceConfig, bigquery.Client, Any]):
    """BigQuery driver implementation paired with `BigQuerySource`.

    `CursorT` is `Any`: BigQuery has no DB-API cursor and does not satisfy
    `_CursorLike`. Streaming and partition sizing run against the
    `bigquery.Client` + `bigquery.Table` objects directly, not via a
    shared `cursor.execute(...)` flow, so the base class's `cursor`-based
    partition / chunk math is bypassed here.
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def connect(
        self,
        config: BigQuerySourceConfig,
        team_id: int,
        auth: BigQueryAuthInfo | None = None,
        location: str | None = None,
    ) -> Iterator[bigquery.Client]:
        region = _resolve_region(config)
        resolved_location = location if location is not None else region
        if auth is None:
            auth = resolve_bigquery_auth(config, team_id)

        with bigquery_client(auth.project_id, resolved_location, auth.credentials) as bq:
            yield bq

    # ------------------------------------------------------------------
    # Listing — batch queries run once during `get_schemas`
    # ------------------------------------------------------------------

    def get_columns(
        self,
        conn: bigquery.Client,
        config: BigQuerySourceConfig,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:
        schema_list: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)

        try:
            # `conn.query()` eagerly creates the BigQuery job (POST .../jobs) and triggers the
            # lazy service-account token refresh, so a `Forbidden` (e.g. missing
            # `bigquery.jobs.create`) or auth failure surfaces here rather than at `result()`.
            # Both calls must sit inside the try so a permission-denied account degrades to
            # "no new schemas" instead of crashing schema discovery.
            query = conn.query(
                f"SELECT table_name, column_name, data_type, is_nullable FROM `{_resolve_dataset_id(config)}.INFORMATION_SCHEMA.COLUMNS` ORDER BY table_name ASC",
                project=_resolve_query_project(config),
            )
            rows = query.result()
        except Forbidden:
            structlog.get_logger().warning(
                "Could not obtain new schemas from BigQuery due to missing permissions on '%s.INFORMATION_SCHEMA.COLUMNS'",
                config.dataset_id,
            )
            return {}
        except TypeError as e:
            # See `BigQueryTokenRefreshError`: google-auth raises an opaque
            # `TypeError: string indices must be integers` when the OAuth token endpoint
            # returns a non-JSON-object 200. Anything else is a genuine bug — let it propagate.
            if "string indices must be integers" not in str(e):
                raise
            raise BigQueryTokenRefreshError(
                f"{BIGQUERY_TOKEN_RESPONSE_ERROR}. Please re-upload your service account key file and verify its token_uri."
            ) from e

        for row in rows:
            schema_list[row.table_name].append((row.column_name, row.data_type, row.is_nullable == "YES"))

        # Filter out PostHog's own temp destination tables — they live in
        # the user's dataset only because BigQuery's Storage API can't
        # stream views/materialized views without copying to a real table
        # first.
        temp_prefix = build_destination_table_prefix(None)
        schema_list = {k: v for k, v in schema_list.items() if not k.startswith(temp_prefix)}

        if names is not None:
            names_set = set(names)
            schema_list = {k: v for k, v in schema_list.items() if k in names_set}

        return dict(schema_list)

    def get_primary_keys(
        self,
        conn: bigquery.Client,
        config: BigQuerySourceConfig,
        tables: list[str],
    ) -> dict[str, list[str] | None]:
        if not tables:
            return {}

        project = _resolve_query_project(config)
        dataset_id = _resolve_dataset_id(config)

        # Join against INFORMATION_SCHEMA.COLUMNS so a PK constraint that
        # references a column already dropped (stale metadata between
        # constraint and column catalogs) doesn't leak into
        # `detected_primary_keys` and corrupt downstream dedup.
        #
        # KEY_COLUMN_USAGE.column_name is sometimes returned as
        # `<table>.<column>` and sometimes plain `<column>` depending on
        # the BigQuery region / metadata version, hence the
        # `removeprefix` below — the JOIN has to tolerate both shapes or
        # half the rows get dropped.
        query = f"""
        SELECT tc.table_name, kcu.column_name
        FROM `{dataset_id}`.INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
        JOIN `{dataset_id}`.INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
        ON tc.constraint_name = kcu.constraint_name
        JOIN `{dataset_id}`.INFORMATION_SCHEMA.COLUMNS c
        ON kcu.table_name = c.table_name
        AND (
            kcu.column_name = c.column_name
            OR kcu.column_name = CONCAT(kcu.table_name, '.', c.column_name)
        )
        WHERE tc.constraint_type = 'PRIMARY KEY'
        """

        constraint_pks: dict[str, list[str]] = collections.defaultdict(list)
        try:
            job = conn.query(query, job_config=QueryJobConfig(), project=project)
            for row in job.result():
                table_name = row["table_name"]
                col_name = row["column_name"].removeprefix(f"{table_name}.")
                constraint_pks[table_name].append(col_name)
        except Exception as e:
            structlog.get_logger().warning("Failed to detect primary keys for BigQuery schemas", exc_info=e)
            return {}

        tables_set = set(tables)
        return {table_name: pks for table_name, pks in constraint_pks.items() if table_name in tables_set}

    def get_leading_index_columns(
        self,
        conn: bigquery.Client,
        config: BigQuerySourceConfig,
        tables: list[str],
    ) -> dict[str, set[str]] | None:
        """Return columns that act as the leading "index" per BigQuery table.

        BigQuery doesn't have B-tree indexes; predicate pushdown for `WHERE col >= …`
        is accelerated by:
          - The partition column (INFORMATION_SCHEMA.COLUMNS.is_partitioning_column = 'YES')
          - The leading clustering column (clustering_ordinal_position = 1)
        Both are equally effective for skipping data, so we treat both as indexed.

        Returns None on discovery failure so callers default to no warning. Tables
        without partitioning or clustering map to an empty set so the UI warns for
        them.
        """
        if not tables:
            return {}

        try:
            result: dict[str, set[str]] = {table: set() for table in tables}

            project = _resolve_query_project(config)

            query = f"""
            SELECT table_name, column_name
            FROM `{_resolve_dataset_id(config)}`.INFORMATION_SCHEMA.COLUMNS
            WHERE is_partitioning_column = 'YES'
               OR clustering_ordinal_position = 1
            """

            job = conn.query(query, job_config=QueryJobConfig(), project=project)
            for row in job.result():
                table_name = row["table_name"]
                if table_name in result:
                    result[table_name].add(row["column_name"])
        except Exception as e:
            structlog.get_logger().warning("Failed to detect partitioning/clustering for BigQuery schemas", exc_info=e)
            return None

        return result

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return filter_bigquery_incremental_fields

    # ------------------------------------------------------------------
    # Pipeline build — the dlt `SourceResponse` for a single table
    # ------------------------------------------------------------------

    def build_pipeline(self, config: BigQuerySourceConfig, inputs: SourceInputs) -> SourceResponse:
        auth = resolve_bigquery_auth(config, inputs.team_id)
        region = _resolve_region(config)
        dataset_project_id = _resolve_dataset_project_id(config)
        project_id = _resolve_project_id(config)
        destination_table_dataset_id = _resolve_dataset_id(config)

        if (
            config.temporary_dataset
            and config.temporary_dataset.enabled
            and config.temporary_dataset.temporary_dataset_id is not None
            and _normalize_identifier(config.temporary_dataset.temporary_dataset_id) != ""
        ):
            destination_table_dataset_id = _normalize_identifier(config.temporary_dataset.temporary_dataset_id)

        # Including the schema ID in table prefix ensures we only delete tables
        # from this schema, and that if we fail we will clean up any previous
        # execution's tables.
        # Table names in BigQuery can have up to 1024 bytes, so we can be pretty
        # relaxed with using a relatively long UUID as part of the prefix.
        destination_table_prefix = build_destination_table_prefix(inputs.schema_id)

        destination_table = f"{auth.project_id}.{destination_table_dataset_id}.{destination_table_prefix}_{inputs.job_id.replace('-', '_')}_{str(datetime.now().timestamp()).replace('.', '')}"

        delete_all_temp_destination_tables(
            dataset_id=destination_table_dataset_id,
            table_prefix=destination_table_prefix,
            project_id=auth.project_id,
            location=region,
            dataset_project_id=dataset_project_id,
            credentials=auth.credentials,
            logger=inputs.logger,
        )

        try:
            return self._build_source_response(
                config=config,
                inputs=inputs,
                region=region,
                dataset_project_id=dataset_project_id,
                bq_destination_table_id=destination_table,
                auth=auth,
            )
        finally:
            # Delete the destination table (if it exists) after we're done with it
            delete_table(
                table_id=destination_table,
                project_id=auth.project_id,
                location=region,
                credentials=auth.credentials,
            )
            inputs.logger.info(f"Deleting bigquery temp destination table: {destination_table}")

    def _build_source_response(
        self,
        config: BigQuerySourceConfig,
        inputs: SourceInputs,
        region: str | None,
        dataset_project_id: str | None,
        bq_destination_table_id: str,
        auth: BigQueryAuthInfo,
        partition_size_bytes: int = DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
    ) -> SourceResponse:
        """Produce a pipeline source for BigQuery.

        Iterates rows in `pyarrow.Table` chunks using BigQuery's Storage API
        for higher quota and lower cost vs. row-by-row reads.
        """
        table_name = inputs.schema_name
        if not table_name:
            raise ValueError("Table name is missing")

        should_use_incremental_field = inputs.should_use_incremental_field
        incremental_field = inputs.incremental_field if should_use_incremental_field else None
        incremental_field_type = inputs.incremental_field_type if should_use_incremental_field else None
        db_incremental_field_last_value = (
            inputs.db_incremental_field_last_value if should_use_incremental_field else None
        )
        enabled_columns = inputs.enabled_columns
        row_filters = inputs.row_filters
        logger = inputs.logger

        project_id = auth.project_id
        location = region
        credentials = auth.credentials

        project_id_for_dataset = dataset_project_id or project_id
        name = NamingConvention.normalize_identifier(table_name)
        fully_qualified_table_name = f"{project_id_for_dataset}.{_resolve_dataset_id(config)}.{table_name}"

        with bigquery_client(project_id=project_id, location=location, credentials=credentials) as bq_client:
            bq_table = bq_client.get_table(fully_qualified_table_name)
            primary_keys = _get_primary_keys_for_table(bq_table, bq_client)
            partition_settings = _get_partition_settings(bq_table, bq_client, partition_size_bytes=partition_size_bytes)
            has_duplicate_keys = _has_duplicate_primary_keys(bq_table, bq_client, primary_keys)
            rows_to_sync = _get_rows_to_sync(
                bq_table,
                bq_client,
                should_use_incremental_field,
                db_incremental_field_last_value,
                logger,
                incremental_field,
                incremental_field_type,
                row_filters=row_filters,
            )

        def get_rows(max_table_size: int) -> collections.abc.Iterator[pa.Table]:
            with bigquery_client(project_id=project_id, location=location, credentials=credentials) as bq_client:
                bq_table = bq_client.get_table(fully_qualified_table_name)

                # Query path projects into the temp table; direct-storage path projects via
                # `selected_fields` on the read session.
                projected_columns = compute_projected_columns(enabled_columns, primary_keys, incremental_field)
                storage_selected_fields: list[str] | None = None

                if should_use_incremental_field:
                    # This is only done because incremental syncs require progress tracking.
                    # This requirement means we need to enforce an order, as otherwise
                    # progress could move ahead of the current stream. Thus, we need to run
                    # a query job that moves all the data in `incremental_field` order to a
                    # temporary table given by `bq_destination_table_id`.
                    # TODO: Think about whether this is at all necessary. We (and our users)
                    # are paying a (potentially high) cost to run this query job and store
                    # this data, when we could instead give up tracking and read it.
                    query, query_parameters = _get_query(
                        should_use_incremental_field,
                        db_incremental_field_last_value,
                        bq_table,
                        incremental_field,
                        incremental_field_type,
                        enabled_columns=enabled_columns,
                        primary_keys=primary_keys,
                        row_filters=row_filters,
                    )

                    destination_table = bigquery.Table(bq_destination_table_id)
                    job_config = QueryJobConfig(destination=destination_table, query_parameters=query_parameters)
                    job = bq_client.query(query, job_config=job_config, project=bq_table.project)
                    _ = job.result()

                    bq_table = bq_client.get_table(destination_table)

                elif bq_table.table_type in ("VIEW", "MATERIALIZED_VIEW", "EXTERNAL") or row_filters:
                    # BigQuery storage API does not support reading directly from views or
                    # materialized views, nor can it apply row filters. So, similarly to
                    # incremental runs, we copy the (optionally filtered) results to a temporary
                    # table first, then read that table via the storage API.
                    query, query_parameters = _get_query(
                        should_use_incremental_field,
                        db_incremental_field_last_value,
                        bq_table,
                        incremental_field,
                        incremental_field_type,
                        enabled_columns=enabled_columns,
                        primary_keys=primary_keys,
                        row_filters=row_filters,
                    )

                    destination_table = bigquery.Table(bq_destination_table_id)
                    job_config = QueryJobConfig(destination=destination_table, query_parameters=query_parameters)
                    job = bq_client.query(query, job_config=job_config, project=bq_table.project)
                    _ = job.result()

                    bq_table = bq_client.get_table(destination_table)

                else:
                    if projected_columns is not None:
                        storage_selected_fields = projected_columns

                requested_session = bigquery_storage.ReadSession(
                    table=bq_table.to_bqstorage(),
                    data_format=bigquery_storage.DataFormat.ARROW,
                    read_options=bigquery_storage.ReadSession.TableReadOptions(
                        selected_fields=storage_selected_fields or [],
                        arrow_serialization_options=bigquery_storage.ArrowSerializationOptions(
                            # LZ4 offers a good trade-off of low resource usage for compression, so
                            # as an initial value without further testing it should do fine. That being said,
                            # TODO: Evaluate if ZSTD is a better alternative for our use case.
                            buffer_compression=bigquery_storage.ArrowSerializationOptions.CompressionCodec.LZ4_FRAME
                        ),
                    ),
                )
                with bigquery_storage_read_client(credentials=credentials) as bq_storage:
                    read_session = bq_storage.create_read_session(
                        parent="projects/{}".format(bq_table.project),
                        read_session=requested_session,
                        # TODO: Currently, single stream. Could multi-thread here for performance.
                        max_stream_count=1,
                    )

                    if not read_session.streams:
                        # Empty table, nothing to read
                        return

                    stream_name = read_session.streams[0].name
                    read_rows_stream = bq_storage.read_rows(stream_name)
                    rows_iterator = read_rows_stream.rows()

                    record_batches = []
                    table_size_bytes = 0
                    for page in rows_iterator.pages:
                        record_batch = page.to_arrow()
                        # TODO: Perhaps we should support slicing record batches like we do in batch exports.
                        table_size_bytes += record_batch.get_total_buffer_size()
                        record_batches.append(record_batch)

                        if table_size_bytes > max_table_size:
                            yield pa.Table.from_batches(record_batches)
                            record_batches = []
                            table_size_bytes = 0

                    if record_batches:
                        yield pa.Table.from_batches(record_batches)

        return SourceResponse(
            name=name,
            items=lambda: get_rows(DEFAULT_TABLE_SIZE_BYTES),
            primary_keys=primary_keys,
            partition_count=partition_settings.partition_count if partition_settings else None,
            partition_size=partition_settings.partition_size if partition_settings else None,
            rows_to_sync=rows_to_sync,
            has_duplicate_primary_keys=has_duplicate_keys,
        )
