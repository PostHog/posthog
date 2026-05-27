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
from datetime import date, datetime
from typing import Any

import pyarrow as pa
import structlog
from google.api_core.exceptions import Forbidden
from google.auth.transport.requests import AuthorizedSession
from google.cloud import bigquery, bigquery_storage
from google.cloud.bigquery.job import QueryJobConfig
from google.oauth2 import service_account
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.helpers import (
    incremental_type_to_initial_value,
    incremental_type_to_operator,
)
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_TABLE_SIZE_BYTES
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES
from posthog.temporal.data_imports.sources.common.http import DEFAULT_RETRY, TrackedHTTPAdapter
from posthog.temporal.data_imports.sources.common.sql.implementation import SQLSourceImplementation
from posthog.temporal.data_imports.sources.common.sql.incremental import IncrementalFieldFilter
from posthog.temporal.data_imports.sources.generated_configs import BigQuerySourceConfig

from products.data_warehouse.backend.types import IncrementalFieldType, PartitionSettings

__all__ = [
    "BigQueryImplementation",
    "bigquery_client",
    "bigquery_storage_read_client",
    "build_destination_table_prefix",
    "delete_all_temp_destination_tables",
    "delete_table",
    "filter_bigquery_incremental_fields",
    "validate_bigquery_credentials",
]


def build_destination_table_prefix(schema_id: str | None) -> str:
    return f"__posthog_import_{schema_id.replace('-', '_') if schema_id else ''}"


def _resolve_region(config: BigQuerySourceConfig) -> str | None:
    if (
        config.use_custom_region
        and config.use_custom_region.enabled
        and config.use_custom_region.region is not None
        and config.use_custom_region.region != ""
    ):
        return config.use_custom_region.region
    return None


def _resolve_dataset_project_id(config: BigQuerySourceConfig) -> str | None:
    if (
        config.dataset_project
        and config.dataset_project.enabled
        and config.dataset_project.dataset_project_id is not None
        and config.dataset_project.dataset_project_id != ""
    ):
        return config.dataset_project.dataset_project_id
    return None


@contextlib.contextmanager
def bigquery_client(
    project_id: str,
    location: str | None,
    private_key: str,
    private_key_id: str,
    client_email: str,
    token_uri: str,
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


def delete_table(
    table_id: str,
    project_id: str,
    location: str | None,
    private_key: str,
    private_key_id: str,
    client_email: str,
    token_uri: str,
) -> None:
    with bigquery_client(project_id, location, private_key, private_key_id, client_email, token_uri) as bq:
        bq.delete_table(table_id, not_found_ok=True)


def delete_all_temp_destination_tables(
    dataset_id: str,
    table_prefix: str,
    project_id: str,
    location: str | None,
    dataset_project_id: str | None,
    private_key: str,
    private_key_id: str,
    client_email: str,
    token_uri: str,
    logger: None | FilteringBoundLogger,
) -> None:
    with bigquery_client(project_id, location, private_key, private_key_id, client_email, token_uri) as bq:
        try:
            tables = bq.list_tables(bq.dataset(dataset_id, project=dataset_project_id or project_id))
            for table in tables:
                if table.table_id.startswith(table_prefix):
                    bq.delete_table(table.reference)
                    if logger:
                        logger.debug(f"Deleted bigquery table {table.table_id}")
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
    dataset_id: str, key_file: dict[str, str], dataset_project_id: str | None, location: str | None
) -> bool:
    project_id = key_file.get("project_id")
    private_key = key_file.get("private_key")
    private_key_id = key_file.get("private_key_id")
    client_email = key_file.get("client_email")
    token_uri = key_file.get("token_uri")

    if not project_id or not private_key or not private_key_id or not client_email or not token_uri:
        return False

    with bigquery_client(project_id, location, private_key, private_key_id, client_email, token_uri) as bq:
        try:
            bq.list_tables(
                bq.dataset(dataset_id, project=dataset_project_id or project_id),
                retry=bigquery.DEFAULT_RETRY.with_timeout(5),
            )
            return True
        except Exception as e:
            capture_exception(e)
            return False


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

        logger.debug("_get_rows_to_sync: No results returned. Using 0 as rows to sync")

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

        operator = incremental_type_to_operator(incremental_field_type)
        return f"""
            SELECT * FROM `{bq_table.dataset_id}`.`{bq_table.table_id}`
            WHERE `{incremental_field}` {operator} {last_value}
            ORDER BY `{incremental_field}` ASC
            """

    return f"SELECT * FROM `{bq_table.dataset_id}`.`{bq_table.table_id}`"


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
    def connect(self, config: BigQuerySourceConfig) -> Iterator[bigquery.Client]:
        region = _resolve_region(config)
        with bigquery_client(
            config.key_file.project_id,
            region,
            config.key_file.private_key,
            config.key_file.private_key_id,
            config.key_file.client_email,
            config.key_file.token_uri,
        ) as bq:
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

        query = conn.query(
            f"SELECT table_name, column_name, data_type, is_nullable FROM `{config.dataset_id}.INFORMATION_SCHEMA.COLUMNS` ORDER BY table_name ASC",
            project=config.dataset_project.dataset_project_id
            if config.dataset_project and config.dataset_project.enabled
            else config.key_file.project_id,
        )
        try:
            rows = query.result()
        except Forbidden:
            structlog.get_logger().warning(
                "Could not obtain new schemas from BigQuery due to missing permissions on '%s.INFORMATION_SCHEMA.COLUMNS'",
                config.dataset_id,
            )
            return {}

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

        project = (
            config.dataset_project.dataset_project_id
            if config.dataset_project and config.dataset_project.enabled
            else config.key_file.project_id
        )

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
        FROM `{config.dataset_id}`.INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
        JOIN `{config.dataset_id}`.INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
        ON tc.constraint_name = kcu.constraint_name
        JOIN `{config.dataset_id}`.INFORMATION_SCHEMA.COLUMNS c
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

            project = (
                config.dataset_project.dataset_project_id
                if config.dataset_project and config.dataset_project.enabled
                else config.key_file.project_id
            )

            query = f"""
            SELECT table_name, column_name
            FROM `{config.dataset_id}`.INFORMATION_SCHEMA.COLUMNS
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
        if not config.key_file.private_key:
            raise ValueError(f"Missing private key for BigQuery: '{inputs.job_id}'")

        region = _resolve_region(config)
        dataset_project_id = _resolve_dataset_project_id(config)
        destination_table_dataset_id = config.dataset_id

        if (
            config.temporary_dataset
            and config.temporary_dataset.enabled
            and config.temporary_dataset.temporary_dataset_id is not None
            and config.temporary_dataset.temporary_dataset_id != ""
        ):
            destination_table_dataset_id = config.temporary_dataset.temporary_dataset_id

        # Including the schema ID in table prefix ensures we only delete tables
        # from this schema, and that if we fail we will clean up any previous
        # execution's tables.
        # Table names in BigQuery can have up to 1024 bytes, so we can be pretty
        # relaxed with using a relatively long UUID as part of the prefix.
        destination_table_prefix = build_destination_table_prefix(inputs.schema_id)

        destination_table = f"{config.key_file.project_id}.{destination_table_dataset_id}.{destination_table_prefix}_{inputs.job_id.replace('-', '_')}_{str(datetime.now().timestamp()).replace('.', '')}"

        delete_all_temp_destination_tables(
            dataset_id=destination_table_dataset_id,
            table_prefix=destination_table_prefix,
            project_id=config.key_file.project_id,
            location=region,
            dataset_project_id=dataset_project_id,
            private_key=config.key_file.private_key,
            private_key_id=config.key_file.private_key_id,
            client_email=config.key_file.client_email,
            token_uri=config.key_file.token_uri,
            logger=inputs.logger,
        )

        try:
            return self._build_source_response(
                config=config,
                inputs=inputs,
                region=region,
                dataset_project_id=dataset_project_id,
                bq_destination_table_id=destination_table,
            )
        finally:
            # Delete the destination table (if it exists) after we're done with it
            delete_table(
                table_id=destination_table,
                project_id=config.key_file.project_id,
                location=region,
                private_key=config.key_file.private_key,
                private_key_id=config.key_file.private_key_id,
                client_email=config.key_file.client_email,
                token_uri=config.key_file.token_uri,
            )
            inputs.logger.info(f"Deleting bigquery temp destination table: {destination_table}")

    def _build_source_response(
        self,
        config: BigQuerySourceConfig,
        inputs: SourceInputs,
        region: str | None,
        dataset_project_id: str | None,
        bq_destination_table_id: str,
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
        logger = inputs.logger

        project_id = config.key_file.project_id
        location = region
        private_key = config.key_file.private_key
        private_key_id = config.key_file.private_key_id
        client_email = config.key_file.client_email
        token_uri = config.key_file.token_uri

        project_id_for_dataset = dataset_project_id or project_id
        name = NamingConvention.normalize_identifier(table_name)
        fully_qualified_table_name = f"{project_id_for_dataset}.{config.dataset_id}.{table_name}"

        with bigquery_client(
            project_id=project_id,
            location=location,
            private_key=private_key,
            private_key_id=private_key_id,
            client_email=client_email,
            token_uri=token_uri,
        ) as bq_client:
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
            )

        def get_rows(max_table_size: int) -> collections.abc.Iterator[pa.Table]:
            with bigquery_client(
                project_id=project_id,
                location=location,
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
            items=lambda: get_rows(DEFAULT_TABLE_SIZE_BYTES),
            primary_keys=primary_keys,
            partition_count=partition_settings.partition_count if partition_settings else None,
            partition_size=partition_settings.partition_size if partition_settings else None,
            rows_to_sync=rows_to_sync,
            has_duplicate_primary_keys=has_duplicate_keys,
        )
