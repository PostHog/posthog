import collections.abc
import contextlib
import typing

import pyarrow as pa
from dlt.common.normalizers.naming.snake_case import NamingConvention
from google.cloud import bigquery, bigquery_storage
from google.cloud.bigquery.job import QueryJobConfig
from google.oauth2 import service_account

from posthog.temporal.data_imports.pipelines.bigquery import bigquery_client
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_TABLE_SIZE_BYTES
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.warehouse.types import IncrementalFieldType


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
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )

    client = bigquery_storage.BigQueryReadClient(credentials=credentials)

    yield client


def get_primary_keys(table: bigquery.Table, client: bigquery.Client) -> list[str] | None:
    """Attempt to fetch primary keys for a BigQuery table.

    This function is compatible with SQLAlchemy source:
    SQLAlchemy does not attempt to query table constraints, so we end up defaulting
    to "id". We will also default to "id" if the column is present in `table`.

    Otherwise, we will also attempt to look at table constraints to find primary keys.
    """
    existing_fields = {field.name for field in table.schema}
    if "id" in existing_fields:
        return ["id"]

    query = f"""
    SELECT constraint_name FROM `{table.dataset_id}`.INFORMATION_SCHEMA.TABLE_CONSTRAINTS
    WHERE table_name = '{table.table_id}'
      AND constraint_type = 'PRIMARY KEY'
    """

    job_config = QueryJobConfig()
    job = client.query(query, job_config=job_config)

    primary_keys = []
    for row in job.result():
        field_name = row[0].removeprefix(f"{table.table_id}.")

        if field_name not in existing_fields:
            return None

        primary_keys.append(field_name)

    if not primary_keys:
        return None
    return primary_keys


def bigquery_source(
    project_id: str,
    dataset_id: str,
    table_name: str,
    private_key: str,
    private_key_id: str,
    client_email: str,
    token_uri: str,
    is_incremental: bool,
    bq_destination_table_id: str,
    db_incremental_field_last_value: typing.Any,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    """Produce a pipeline source for BigQuery.

    This source will iterate through rows in `pyarrow.Table` objects using BigQuery's
    Storage API as much as possible due to higher quotas and lower cost compared to
    alternatives.
    """
    name = NamingConvention().normalize_identifier(table_name)
    fully_qualified_table_name = f"{project_id}.{dataset_id}.{table_name}"

    with bigquery_client(
        project_id=project_id,
        private_key=private_key,
        private_key_id=private_key_id,
        client_email=client_email,
        token_uri=token_uri,
    ) as bq_client:
        bq_table = bq_client.get_table(fully_qualified_table_name)
        primary_keys = get_primary_keys(bq_table, bq_client)

    def get_rows(max_table_size: int) -> collections.abc.Iterator[pa.Table]:
        with bigquery_client(
            project_id=project_id,
            private_key=private_key,
            private_key_id=private_key_id,
            client_email=client_email,
            token_uri=token_uri,
        ) as bq_client:
            bq_table = bq_client.get_table(fully_qualified_table_name)

            if is_incremental:
                # This is only done because incremental syncs require progress tracking.
                # This requirement means we need to enforce an order, as otherwise
                # progress could move ahead of the current stream. Thus, we need to run
                # a query job that moves all the data in `incremental_field` order to a
                # temporary table given by `bq_destination_table_id`.
                # TODO: Think about whether this is at all necessary. We (and our users)
                # are paying a (potentially high) cost to run this query job and store
                # this data, when we could instead give up tracking and read it.
                if incremental_field is None or incremental_field_type is None:
                    raise ValueError("incremental_field and incremental_field_type can't be None")

                if db_incremental_field_last_value is None:
                    last_value = incremental_type_to_initial_value(incremental_field_type)
                else:
                    last_value = db_incremental_field_last_value

                query = f"""
                SELECT * FROM `{bq_table.dataset_id}`.`{bq_table.table_id}`
                WHERE `{incremental_field}` >= {last_value}
                ORDER BY `{incremental_field}` ASC
                """

                destination_table = bigquery.Table(bq_destination_table_id)
                job_config = QueryJobConfig(destination=destination_table)
                job = bq_client.query(query, job_config=job_config)
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

    return SourceResponse(name=name, items=get_rows(DEFAULT_TABLE_SIZE_BYTES), primary_keys=primary_keys)
