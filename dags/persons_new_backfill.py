"""Dagster job for backfilling posthog_persons data from source to destination Postgres database."""

from typing import Any, Optional

import dagster
import psycopg2
import psycopg2.extras

from dags.common import JobOwners


class PersonsNewBackfillConfig(dagster.Config):
    """Configuration for the persons new backfill job."""

    chunk_size: int = 1_000_000  # ID range per chunk
    batch_size: int = 100_000  # Records per batch insert
    source_table: str = "posthog_persons"
    destination_table: str = "posthog_persons_new"
    max_id: Optional[int] = None  # Optional override for max ID to resume from partial state


@dagster.op
def get_id_range(
    context: dagster.OpExecutionContext,
    config: PersonsNewBackfillConfig,
    source_postgres: dagster.ResourceParam[psycopg2.extensions.connection],
) -> tuple[int, int]:
    """
    Query source database for MIN(id) and optionally MAX(id) from posthog_persons table.
    If max_id is provided in config, uses that instead of querying.
    Returns tuple (min_id, max_id).
    """
    with source_postgres.cursor() as cursor:
        # Always query for min_id
        min_query = f"SELECT MIN(id) as min_id FROM {config.source_table}"
        context.log.info(f"Querying min ID: {min_query}")
        cursor.execute(min_query)
        min_result = cursor.fetchone()

        if min_result is None or min_result["min_id"] is None:
            context.log.exception("Source table is empty or has no valid IDs")
            raise dagster.Failure("Source table is empty or has no valid IDs")

        min_id = int(min_result["min_id"])

        # Use config max_id if provided, otherwise query database
        if config.max_id is not None:
            max_id = config.max_id
            context.log.info(f"Using configured max_id override: {max_id}")
        else:
            max_query = f"SELECT MAX(id) as max_id FROM {config.source_table}"
            context.log.info(f"Querying max ID: {max_query}")
            cursor.execute(max_query)
            max_result = cursor.fetchone()

            if max_result is None or max_result["max_id"] is None:
                context.log.exception("Source table has no valid max ID")
                raise dagster.Failure("Source table has no valid max ID")

            max_id = int(max_result["max_id"])

        # Validate that max_id >= min_id
        if max_id < min_id:
            error_msg = f"Invalid ID range: max_id ({max_id}) < min_id ({min_id})"
            context.log.error(error_msg)
            raise dagster.Failure(error_msg)

        context.log.info(f"ID range: min={min_id}, max={max_id}, total_ids={max_id - min_id + 1}")
        context.add_output_metadata(
            {
                "min_id": dagster.MetadataValue.int(min_id),
                "max_id": dagster.MetadataValue.int(max_id),
                "max_id_source": dagster.MetadataValue.text("config" if config.max_id is not None else "database"),
                "total_ids": dagster.MetadataValue.int(max_id - min_id + 1),
            }
        )

        return (min_id, max_id)


@dagster.op(out=dagster.DynamicOut(tuple[int, int]))
def create_chunks(
    context: dagster.OpExecutionContext,
    config: PersonsNewBackfillConfig,
    id_range: tuple[int, int],
):
    """
    Divide ID space into chunks of chunk_size.
    Yields DynamicOutput for each chunk.
    """
    min_id, max_id = id_range
    chunk_size = config.chunk_size

    chunk_min = min_id
    chunk_num = 0

    while chunk_min <= max_id:
        chunk_max = min(chunk_min + chunk_size - 1, max_id)
        chunk_key = f"chunk_{chunk_min}_{chunk_max}"

        context.log.info(f"Creating chunk {chunk_num}: {chunk_min} to {chunk_max}")
        yield dagster.DynamicOutput(
            value=(chunk_min, chunk_max),
            mapping_key=chunk_key,
        )

        chunk_min = chunk_max + 1
        chunk_num += 1

    context.log.info(f"Created {chunk_num} chunks total")


def _get_table_columns(connection: psycopg2.extensions.connection, schema: str, table_name: str) -> list[str]:
    """Get column names for a table."""
    with connection.cursor() as cursor:
        query = """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """
        cursor.execute(query, (schema, table_name))
        return [row["column_name"] for row in cursor.fetchall()]


@dagster.op
def copy_chunk(
    context: dagster.OpExecutionContext,
    config: PersonsNewBackfillConfig,
    chunk: tuple[int, int],
    source_postgres: dagster.ResourceParam[psycopg2.extensions.connection],
    destination_postgres: dagster.ResourceParam[psycopg2.extensions.connection],
) -> dict[str, Any]:
    """
    Copy a chunk of records from source to destination database.
    Processes in batches of batch_size records.
    """
    chunk_min, chunk_max = chunk
    batch_size = config.batch_size
    source_table = config.source_table
    destination_table = config.destination_table

    context.log.info(f"Starting chunk copy: {chunk_min} to {chunk_max}")

    # Get column names from source table (assuming public schema)
    try:
        source_columns = _get_table_columns(source_postgres, "public", source_table)
        if not source_columns:
            raise dagster.Failure(f"Source table {source_table} has no columns or doesn't exist")

        # Verify destination table exists and get its columns
        dest_columns = _get_table_columns(destination_postgres, "public", destination_table)
        if not dest_columns:
            raise dagster.Failure(f"Destination table {destination_table} has no columns or doesn't exist")

        # Use intersection of columns that exist in both tables
        columns_to_copy = [col for col in source_columns if col in dest_columns]
        if not columns_to_copy:
            raise dagster.Failure(
                f"No matching columns between source {source_table} and destination {destination_table}"
            )

        context.log.info(f"Copying {len(columns_to_copy)} columns: {', '.join(columns_to_copy)}")

    except Exception as e:
        error_msg = f"Failed to get table schema for chunk {chunk_min}-{chunk_max}: {str(e)}"
        context.log.exception(error_msg)
        raise dagster.Failure(error_msg) from e

    # Build SELECT and INSERT queries
    columns_str = ", ".join(columns_to_copy)
    placeholders = ", ".join(["%s"] * len(columns_to_copy))
    # Use ID-based batching: WHERE id >= batch_start AND id < batch_end ORDER BY id LIMIT batch_size
    select_query = f"SELECT {columns_str} FROM {source_table} WHERE id >= %s AND id <= %s ORDER BY id LIMIT %s"
    insert_query = f"INSERT INTO {destination_table} ({columns_str}) VALUES ({placeholders})"

    total_records_copied = 0
    batch_start_id = chunk_min
    failed_batch_start_id: Optional[int] = None

    try:
        with source_postgres.cursor() as source_cursor, destination_postgres.cursor() as dest_cursor:
            while batch_start_id <= chunk_max:
                try:
                    # Fetch batch from source: WHERE id >= batch_start_id AND id <= chunk_max
                    source_cursor.execute(
                        select_query,
                        (batch_start_id, chunk_max, batch_size),
                    )
                    rows = source_cursor.fetchall()

                    if not rows:
                        # No more rows in this chunk
                        break

                    # Prepare data for batch insert
                    batch_data = []
                    last_id_in_batch = None
                    for row in rows:
                        batch_data.append([row[col] for col in columns_to_copy])
                        # Track the last ID we're processing
                        if "id" in columns_to_copy:
                            id_idx = columns_to_copy.index("id")
                            last_id_in_batch = row[columns_to_copy[id_idx]]

                    # Insert batch into destination
                    psycopg2.extras.execute_batch(
                        dest_cursor,
                        insert_query,
                        batch_data,
                        page_size=batch_size,
                    )
                    destination_postgres.commit()

                    records_in_batch = len(batch_data)
                    total_records_copied += records_in_batch

                    context.log.info(
                        f"Copied batch: {records_in_batch} records "
                        f"(chunk {chunk_min}-{chunk_max}, batch starting at ID {batch_start_id})"
                    )

                    # Update batch_start_id for next iteration
                    # If we got fewer rows than batch_size, we're done
                    if records_in_batch < batch_size:
                        break

                    # Move to next batch: use the last ID + 1
                    if last_id_in_batch is not None:
                        batch_start_id = last_id_in_batch + 1
                    else:
                        # Fallback: increment by batch_size if we can't determine last ID
                        batch_start_id += batch_size

                except Exception as batch_error:
                    failed_batch_start_id = batch_start_id
                    error_msg = (
                        f"Failed to copy batch starting at ID {batch_start_id} "
                        f"in chunk {chunk_min}-{chunk_max}: {str(batch_error)}"
                    )
                    context.log.exception(error_msg)
                    raise dagster.Failure(
                        description=error_msg,
                        metadata={
                            "chunk_min_id": dagster.MetadataValue.int(chunk_min),
                            "chunk_max_id": dagster.MetadataValue.int(chunk_max),
                            "failed_batch_start_id": dagster.MetadataValue.int(failed_batch_start_id)
                            if failed_batch_start_id
                            else dagster.MetadataValue.text("N/A"),
                            "error_message": dagster.MetadataValue.text(str(batch_error)),
                            "records_copied_before_failure": dagster.MetadataValue.int(total_records_copied),
                        },
                    ) from batch_error

    except dagster.Failure:
        # Re-raise Dagster failures as-is (they already have metadata)
        raise
    except Exception as e:
        # Catch any other unexpected errors
        error_msg = f"Unexpected error copying chunk {chunk_min}-{chunk_max}: {str(e)}"
        context.log.exception(error_msg)
        raise dagster.Failure(
            description=error_msg,
            metadata={
                "chunk_min_id": dagster.MetadataValue.int(chunk_min),
                "chunk_max_id": dagster.MetadataValue.int(chunk_max),
                "failed_batch_start_id": dagster.MetadataValue.int(failed_batch_start_id)
                if failed_batch_start_id
                else dagster.MetadataValue.int(batch_start_id),
                "error_message": dagster.MetadataValue.text(str(e)),
                "records_copied_before_failure": dagster.MetadataValue.int(total_records_copied),
            },
        ) from e

    context.log.info(f"Completed chunk {chunk_min}-{chunk_max}: copied {total_records_copied} records")
    context.add_output_metadata(
        {
            "chunk_min": dagster.MetadataValue.int(chunk_min),
            "chunk_max": dagster.MetadataValue.int(chunk_max),
            "records_copied": dagster.MetadataValue.int(total_records_copied),
        }
    )

    return {
        "chunk_min": chunk_min,
        "chunk_max": chunk_max,
        "records_copied": total_records_copied,
    }


@dagster.job(
    config=PersonsNewBackfillConfig,
    tags={"owner": JobOwners.TEAM_CLICKHOUSE.value},
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 4}),
)
def persons_new_backfill_job():
    """
    Backfill posthog_persons data from source to destination Postgres database.
    Divides the ID space into chunks and processes them in parallel.
    """
    id_range = get_id_range()
    chunks = create_chunks(id_range)
    chunks.map(copy_chunk)
