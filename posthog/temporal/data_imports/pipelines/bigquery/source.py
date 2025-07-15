import collections
import collections.abc
import contextlib
import math
import typing
from datetime import date, datetime

import pyarrow as pa
from dlt.common.normalizers.naming.snake_case import NamingConvention
from google.api_core.exceptions import Forbidden
from google.cloud import bigquery, bigquery_storage
from google.cloud.bigquery.job import QueryJobConfig
from google.oauth2 import service_account

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_TABLE_SIZE_BYTES
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
)
from posthog.temporal.data_imports.pipelines.source import config
from posthog.warehouse.types import IncrementalFieldType, PartitionSettings


@config.config
class BigQuerySourceConfig(config.Config):
    dataset_id: str
    project_id: str
    private_key: str
    private_key_id: str
    client_email: str
    token_uri: str
    using_temporary_dataset: bool | None = config.value(converter=config.str_to_bool, default=False)
    temporary_dataset_id: str | None = None
    using_custom_dataset_project: bool | None = config.value(converter=config.str_to_bool, default=False)
    dataset_project_id: str | None = None


def get_schemas(
    config: BigQuerySourceConfig,
    logger: FilteringBoundLogger | None = None,
) -> dict[str, list[tuple[str, str]]]:
    schema_list = collections.defaultdict(list)

    with bigquery_client(
        config.project_id, config.private_key, config.private_key_id, config.client_email, config.token_uri
    ) as bq:
        query = bq.query(
            f"SELECT table_name, column_name, data_type FROM `{config.dataset_id}.INFORMATION_SCHEMA.COLUMNS` ORDER BY table_name ASC",
            project=config.dataset_project_id or config.project_id,
        )
        try:
            rows = query.result()
        except Forbidden:
            if logger:
                logger.warning(
                    "Could not obtain new schemas from BigQuery due to missing permissions on '%s.INFORMATION_SCHEMA.COLUMNS'",
                    config.dataset_id,
                )
            return {}

        for row in rows:
            schema_list[row.table_name].append((row.column_name, row.data_type))

    return schema_list


@contextlib.contextmanager
def bigquery_client(
    project_id: str, private_key: str, private_key_id: str, client_email: str, token_uri: str
) -> typing.Iterator[bigquery.Client]:
    """Manage a BigQuery client."""
    credentials = service_account.Credentials.from_service_account_info(
        {
            "private_key": private_key,
            "private_key_id": private_key_id,
            "token_uri": token_uri,
            "client_email": client_email,
            "project_id": project_id,
        },
        scopes=["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/cloud-platform"],
    )
    client = bigquery.Client(
        project=project_id,
        credentials=credentials,
    )

    try:
        yield client
    finally:
        client.close()


def delete_table(
    table_id: str, project_id: str, private_key: str, private_key_id: str, client_email: str, token_uri: str
) -> None:
    with bigquery_client(project_id, private_key, private_key_id, client_email, token_uri) as bq:
        bq.delete_table(table_id, not_found_ok=True)


def delete_all_temp_destination_tables(
    dataset_id: str,
    table_prefix: str,
    project_id: str,
    dataset_project_id: str | None,
    private_key: str,
    private_key_id: str,
    client_email: str,
    token_uri: str,
    logger: None | FilteringBoundLogger,
) -> None:
    with bigquery_client(project_id, private_key, private_key_id, client_email, token_uri) as bq:
        try:
            tables = bq.list_tables(bq.dataset(dataset_id, project=dataset_project_id or project_id))
            for table in tables:
                if table.table_id.startswith(table_prefix):
                    bq.delete_table(table.reference)
                    if logger:
                        logger.debug(f"Deleted bigquery table {table.table_id}")
        except Exception as e:
            capture_exception(e)


def filter_incremental_fields(columns: list[tuple[str, str]]) -> list[tuple[str, IncrementalFieldType]]:
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, type in columns:
        type = type.upper()
        if type.startswith("TIMESTAMP"):
            results.append((column_name, IncrementalFieldType.Timestamp))
        elif type.startswith("DATE"):
            results.append((column_name, IncrementalFieldType.Date))
        elif type.startswith("DATETIME"):
            results.append((column_name, IncrementalFieldType.DateTime))
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
            results.append((column_name, IncrementalFieldType.Integer))

    return results


def validate_credentials(dataset_id: str, key_file: dict[str, str], dataset_project_id: str | None) -> bool:
    project_id = key_file.get("project_id")
    private_key = key_file.get("private_key")
    private_key_id = key_file.get("private_key_id")
    client_email = key_file.get("client_email")
    token_uri = key_file.get("token_uri")

    if not project_id or not private_key or not private_key_id or not client_email or not token_uri:
        return False

    with bigquery_client(project_id, private_key, private_key_id, client_email, token_uri) as bq:
        try:
            bq.list_tables(
                bq.dataset(dataset_id, project=dataset_project_id or project_id),
                retry=bigquery.DEFAULT_RETRY.with_timeout(5),
            )
            return True
        except Exception as e:
            capture_exception(e)
            return False


@contextlib.contextmanager
def bigquery_storage_read_client(
    project_id: str, private_key: str, private_key_id: str, client_email: str, token_uri: str
):
    """Manage a BigQuery Storage client."""
    credentials = service_account.Credentials.from_service_account_info(
        {
            "private_key": private_key,
            "private_key_id": private_key_id,
            "token_uri": token_uri,
            "client_email": client_email,
            "project_id": project_id,
        },
        scopes=["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/cloud-platform"],
    )

    client = bigquery_storage.BigQueryReadClient(
        credentials=credentials,
    )

    yield client


def get_partition_settings(
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


def get_primary_keys(table: bigquery.Table, client: bigquery.Client) -> list[str] | None:
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


def has_duplicate_primary_keys(table: bigquery.Table, client: bigquery.Client, primary_keys: list[str] | None) -> bool:
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
) -> int:
    try:
        if not should_use_incremental_field:
            table = client.get_table(table)
            if table.num_rows:
                logger.debug(f"_get_rows_to_sync: table.num_rows={table.num_rows}")

                return table.num_rows

        inner_query = _get_query(
            should_use_incremental_field,
            db_incremental_field_last_value,
            table,
            incremental_field,
            incremental_field_type,
        )

        query = f"SELECT COUNT(*) FROM ({inner_query}) as t"

        job_config = QueryJobConfig()
        job = client.query(query, job_config=job_config, project=table.project)

        rows = job.result(page_size=1)
        row = next(rows, None)

        if row and len(row) > 0 and row[0] is not None:
            rows_to_sync_int = int(row[0])
            logger.debug(f"_get_rows_to_sync: rows_to_sync_int={rows_to_sync_int}")
            return rows_to_sync_int

        logger.debug(f"_get_rows_to_sync: No results returned. Using 0 as rows to sync")

        return 0
    except Exception as e:
        logger.debug(f"_get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
        capture_exception(e)

        return 0


def _get_query(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: typing.Any,
    bq_table: bigquery.Table,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> str:
    if should_use_incremental_field:
        if incremental_field is None or incremental_field_type is None:
            raise ValueError("incremental_field and incremental_field_type can't be None")

        if db_incremental_field_last_value is None:
            last_value: int | datetime | date | str = incremental_type_to_initial_value(incremental_field_type)
        else:
            last_value = db_incremental_field_last_value

        if isinstance(last_value, datetime) or isinstance(last_value, date):
            last_value = f"'{last_value.isoformat()}'"

        return f"""
            SELECT * FROM `{bq_table.dataset_id}`.`{bq_table.table_id}`
            WHERE `{incremental_field}` >= {last_value}
            ORDER BY `{incremental_field}` ASC
            """

    return f"SELECT * FROM `{bq_table.dataset_id}`.`{bq_table.table_id}`"


def bigquery_source(
    project_id: str,
    dataset_id: str,
    table_name: str,
    private_key: str,
    private_key_id: str,
    dataset_project_id: str | None,
    client_email: str,
    token_uri: str,
    should_use_incremental_field: bool,
    bq_destination_table_id: str,
    db_incremental_field_last_value: typing.Any,
    logger: FilteringBoundLogger,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
    partition_size_bytes: int = DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
) -> SourceResponse:
    """Produce a pipeline source for BigQuery.

    This source will iterate through rows in `pyarrow.Table` objects using BigQuery's
    Storage API as much as possible due to higher quotas and lower cost compared to
    alternatives.
    """

    project_id_for_dataset = dataset_project_id or project_id
    name = NamingConvention().normalize_identifier(table_name)
    fully_qualified_table_name = f"{project_id_for_dataset}.{dataset_id}.{table_name}"

    with bigquery_client(
        project_id=project_id,
        private_key=private_key,
        private_key_id=private_key_id,
        client_email=client_email,
        token_uri=token_uri,
    ) as bq_client:
        bq_table = bq_client.get_table(fully_qualified_table_name)
        primary_keys = get_primary_keys(bq_table, bq_client)
        partition_settings = get_partition_settings(bq_table, bq_client, partition_size_bytes=partition_size_bytes)
        has_duplicate_keys = has_duplicate_primary_keys(bq_table, bq_client, primary_keys)
        rows_to_sync = _get_rows_to_sync(
            bq_table,
            bq_client,
            should_use_incremental_field,
            db_incremental_field_last_value,
            logger,
            incremental_field,
            incremental_field_type,
        )

    def get_rows(max_table_size: int) -> collections.abc.Iterator[pa.Table]:
        with bigquery_client(
            project_id=project_id,
            private_key=private_key,
            private_key_id=private_key_id,
            client_email=client_email,
            token_uri=token_uri,
        ) as bq_client:
            bq_table = bq_client.get_table(fully_qualified_table_name)

            if should_use_incremental_field:
                # This is only done because incremental syncs require progress tracking.
                # This requirement means we need to enforce an order, as otherwise
                # progress could move ahead of the current stream. Thus, we need to run
                # a query job that moves all the data in `incremental_field` order to a
                # temporary table given by `bq_destination_table_id`.
                # TODO: Think about whether this is at all necessary. We (and our users)
                # are paying a (potentially high) cost to run this query job and store
                # this data, when we could instead give up tracking and read it.
                query = _get_query(
                    should_use_incremental_field,
                    db_incremental_field_last_value,
                    bq_table,
                    incremental_field,
                    incremental_field_type,
                )

                destination_table = bigquery.Table(bq_destination_table_id)
                job_config = QueryJobConfig(destination=destination_table)
                job = bq_client.query(query, job_config=job_config, project=bq_table.project)
                _ = job.result()

                bq_table = bq_client.get_table(destination_table)

            elif bq_table.table_type in ("VIEW", "MATERIALIZED_VIEW", "EXTERNAL"):
                # BigQuery storage API does not support reading directly from views or
                # materialized views. So, similarly to incremental runs, we must copy the
                # results to a temporary table first. In the case of an incremental sync,
                # we already do this for all tables and views, so here we just handle the
                # views or materialized views that are not incremental.
                query = _get_query(
                    should_use_incremental_field,
                    db_incremental_field_last_value,
                    bq_table,
                    incremental_field,
                    incremental_field_type,
                )

                destination_table = bigquery.Table(bq_destination_table_id)
                job_config = QueryJobConfig(destination=destination_table)
                job = bq_client.query(query, job_config=job_config, project=bq_table.project)
                _ = job.result()

                bq_table = bq_client.get_table(destination_table)

            requested_session = bigquery_storage.ReadSession(
                table=bq_table.to_bqstorage(),
                data_format=bigquery_storage.DataFormat.ARROW,
                read_options=bigquery_storage.ReadSession.TableReadOptions(
                    arrow_serialization_options=bigquery_storage.ArrowSerializationOptions(
                        # LZ4 offers a good trade-off of low resource usage for compression, so
                        # as an initial value without further testing it should do fine. That being said,
                        # TODO: Evaluate if ZSTD is a better alternative for our use case.
                        buffer_compression=bigquery_storage.ArrowSerializationOptions.CompressionCodec.LZ4_FRAME
                    )
                ),
            )
            with bigquery_storage_read_client(
                project_id=project_id,
                private_key=private_key,
                private_key_id=private_key_id,
                client_email=client_email,
                token_uri=token_uri,
            ) as bq_storage:
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
        items=get_rows(DEFAULT_TABLE_SIZE_BYTES),
        primary_keys=primary_keys,
        partition_count=partition_settings.partition_count if partition_settings else None,
        partition_size=partition_settings.partition_size if partition_settings else None,
        rows_to_sync=rows_to_sync,
        has_duplicate_primary_keys=has_duplicate_keys,
    )
