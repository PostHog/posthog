import datetime
from typing import Optional

import dagster
from dagster import schedule, job, op, Config, In, Out

from dags.common import JobOwners
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster


class PropertyDefinitionsConfig(Config):
    """Configuration for property definitions ingestion job."""

    # Process a specific hour (ISO format) instead of lookback
    target_hour: Optional[str] = None
    # For backfill runs, we can specify a start and end date
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    # Timeout for query execution in seconds
    max_execution_time: int = 6000


def format_datetime_for_clickhouse(dt: datetime.datetime) -> str:
    """
    Format a datetime object for ClickHouse's toDateTime function.
    Removes timezone information and returns a compatible format.

    Args:
        dt: A datetime object, potentially with timezone info

    Returns:
        A string in format 'YYYY-MM-DD HH:MM:SS' without timezone info
    """
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@op(
    out={"inserted_count": Out(int), "time_window": Out(tuple[str, str])},
)
def ingest_event_properties(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> tuple[int, tuple[str, str]]:
    """
    Ingest event properties from events_recent table into property_definitions table.

    Uses the JSONExtractKeysAndValuesRaw function to extract property keys and values,
    then determines the property type using JSONType.
    """
    # Get config from context
    config_dict = getattr(context, "op_config", {}) or {}

    # Convert to PropertyDefinitionsConfig
    config = PropertyDefinitionsConfig(
        target_hour=config_dict.get("target_hour"),
        start_date=config_dict.get("start_date"),
        end_date=config_dict.get("end_date"),
        max_execution_time=config_dict.get("max_execution_time", 6000),
    )

    # Build the time filter based on config
    if config.start_date and config.end_date:
        # For backfill runs - these should already be in the right format
        time_filter = f"timestamp BETWEEN toDateTime('{config.start_date}') AND toDateTime('{config.end_date}')"
    elif config.target_hour:
        # For processing a specific complete hour
        hour_start = datetime.datetime.fromisoformat(config.target_hour)
        hour_end = hour_start + datetime.timedelta(hours=1)
        start_formatted = format_datetime_for_clickhouse(hour_start)
        end_formatted = format_datetime_for_clickhouse(hour_end)
        time_filter = f"timestamp BETWEEN toDateTime('{start_formatted}') AND toDateTime('{end_formatted}')"
    else:
        # Default to previous complete hour
        now = datetime.datetime.now(datetime.UTC)
        previous_hour = now.replace(minute=0, second=0, microsecond=0) - datetime.timedelta(hours=1)
        hour_end = previous_hour + datetime.timedelta(hours=1)
        start_formatted = format_datetime_for_clickhouse(previous_hour)
        end_formatted = format_datetime_for_clickhouse(hour_end)
        time_filter = f"timestamp BETWEEN toDateTime('{start_formatted}') AND toDateTime('{end_formatted}')"

    # Log the execution parameters
    context.log.info(
        f"Ingesting event properties with target_hour={config.target_hour}, "
        f"start_date={config.start_date}, end_date={config.end_date}, "
        f"time_filter={time_filter}"
    )

    # Query to insert event properties into property_definitions table
    query = f"""
    INSERT INTO property_definitions (* EXCEPT(version))
    SELECT
        team_id,
        team_id as project_id,
        (arrayJoin(JSONExtractKeysAndValuesRaw(properties)) as x).1 as name,
        map(
            34, 'String',
            98, 'Boolean',
            100, 'Numeric',
            105, 'Numeric',
            117, 'Numeric',
            0, NULL
        )[JSONType(x.2)] as property_type,
        event,
        NULL as group_type_index,
        1 as type,
        max(timestamp) as last_seen_at
    FROM events_recent
    WHERE {time_filter}
    GROUP BY team_id, event, name, property_type
    ORDER BY team_id, event, name, property_type NULLS LAST
    LIMIT 1 by team_id, event, name
    SETTINGS max_execution_time = {config.max_execution_time}
    """

    context.log.info("Executing insert query...")
    sync_execute(query)

    # Parse the time range for the count query
    count_time_range = time_filter.split("BETWEEN ")[1]
    start_time, end_time = count_time_range.split(" AND ")

    # Get the number of rows inserted for this specific time window
    count_query = f"""
    SELECT count() FROM property_definitions
    WHERE type = 1 AND last_seen_at BETWEEN {start_time} AND {end_time}
    """

    rows = sync_execute(count_query)[0][0]
    context.log.info(f"Inserted {rows} event property definitions")

    # Return both the count and the time window for later use
    return rows, (start_time, end_time)


@op(
    ins={"event_time_window": In(tuple[str, str])},
    out={"inserted_count": Out(int), "time_window": Out(tuple[str, str])},
)
def ingest_person_properties(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    event_time_window: tuple[str, str],
) -> tuple[int, tuple[str, str]]:
    """
    Ingest person properties from person table into property_definitions table.

    Uses the JSONExtractKeysAndValuesRaw function to extract property keys and values,
    then determines the property type using JSONType.
    """
    # Get config from context
    config_dict = getattr(context, "op_config", {}) or {}

    # Convert to PropertyDefinitionsConfig
    config = PropertyDefinitionsConfig(
        target_hour=config_dict.get("target_hour"),
        start_date=config_dict.get("start_date"),
        end_date=config_dict.get("end_date"),
        max_execution_time=config_dict.get("max_execution_time", 6000),
    )

    # Build the time filter based on config
    if config.start_date and config.end_date:
        # For backfill runs - these should already be in the right format
        time_filter = f"_timestamp BETWEEN toDateTime('{config.start_date}') AND toDateTime('{config.end_date}')"
    elif config.target_hour:
        # For processing a specific complete hour
        hour_start = datetime.datetime.fromisoformat(config.target_hour)
        hour_end = hour_start + datetime.timedelta(hours=1)
        start_formatted = format_datetime_for_clickhouse(hour_start)
        end_formatted = format_datetime_for_clickhouse(hour_end)
        time_filter = f"_timestamp BETWEEN toDateTime('{start_formatted}') AND toDateTime('{end_formatted}')"
    else:
        # Default to previous complete hour
        now = datetime.datetime.now(datetime.UTC)
        previous_hour = now.replace(minute=0, second=0, microsecond=0) - datetime.timedelta(hours=1)
        hour_end = previous_hour + datetime.timedelta(hours=1)
        start_formatted = format_datetime_for_clickhouse(previous_hour)
        end_formatted = format_datetime_for_clickhouse(hour_end)
        time_filter = f"_timestamp BETWEEN toDateTime('{start_formatted}') AND toDateTime('{end_formatted}')"

    # Log the execution parameters
    context.log.info(
        f"Ingesting person properties with target_hour={config.target_hour}, "
        f"start_date={config.start_date}, end_date={config.end_date}, "
        f"time_filter={time_filter}"
    )

    # Query to insert person properties into property_definitions table
    query = f"""
    INSERT INTO property_definitions (* EXCEPT(version))
    SELECT
        team_id,
        team_id as project_id,
        (arrayJoin(JSONExtractKeysAndValuesRaw(properties)) as x).1 as name,
        map(
            34, 'String',
            98, 'Boolean',
            100, 'Numeric',
            105, 'Numeric',
            117, 'Numeric',
            0, NULL
        )[JSONType(x.2)] as property_type,
        NULL as event,
        NULL as group_type_index,
        2 as type,
        max(_timestamp) as last_seen_at
    FROM person
    WHERE {time_filter}
    GROUP BY team_id, name, property_type
    ORDER BY team_id, name, property_type NULLS LAST
    LIMIT 1 by team_id, name
    SETTINGS max_execution_time = {config.max_execution_time}
    """

    context.log.info("Executing insert query...")
    sync_execute(query)

    # Parse the time range for the count query
    count_time_range = time_filter.split("BETWEEN ")[1]
    start_time, end_time = count_time_range.split(" AND ")

    # Get the number of rows inserted for this specific time window
    count_query = f"""
    SELECT count() FROM property_definitions
    WHERE type = 2 AND last_seen_at BETWEEN {start_time} AND {end_time}
    """

    rows = sync_execute(count_query)[0][0]
    context.log.info(f"Inserted {rows} person property definitions")

    # Return both the person count and reuse the event time window (both are needed in optimize)
    return rows, event_time_window


@op(
    ins={"event_count": In(int), "person_count": In(int), "time_window": In(tuple[str, str])},
    out={"total_count": Out(int)},
)
def optimize_property_definitions(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    event_count: int,
    person_count: int,
    time_window: tuple[str, str],
) -> int:
    """
    Run OPTIMIZE on property_definitions table to deduplicate inserted data.

    This runs after both event and person property ingestion completes successfully.
    """
    start_time, end_time = time_window

    context.log.info(f"Running OPTIMIZE TABLE for {event_count} event properties and {person_count} person properties")
    context.log.info(f"Time window: {start_time} to {end_time}")

    # Run OPTIMIZE after all inserts to merge duplicates using the ReplacingMergeTree's version column
    sync_execute("OPTIMIZE TABLE property_definitions FINAL")

    # Get the total number of property definitions for this time window
    count_query = f"""
    SELECT count() FROM property_definitions
    WHERE last_seen_at BETWEEN {start_time} AND {end_time}
    """

    total = sync_execute(count_query)[0][0]
    context.log.info(f"Total property definitions after optimization: {total}")

    return total


@job(
    name="property_definitions_ingestion",
    tags={"owner": JobOwners.TEAM_CLICKHOUSE.value},
)
def property_definitions_ingestion_job():
    """
    Job that ingests properties into the property_definitions table.

    This job runs in the following sequence:
    1. Ingest event properties
    2. Ingest person properties
    3. Run OPTIMIZE FINAL on the table
    """
    event_count, time_window = ingest_event_properties()
    person_count, time_window = ingest_person_properties(event_time_window=time_window)
    optimize_property_definitions(event_count, person_count, time_window)


@schedule(
    job=property_definitions_ingestion_job,
    cron_schedule="5 * * * *",  # Run 5 minutes after the hour
    execution_timezone="UTC",
)
def property_definitions_hourly_schedule(context):
    """
    Schedule the property definitions ingestion job to run hourly.

    Runs 5 minutes after each hour to process data from the previous hour.
    """
    # Calculate the previous hour in ISO format
    now = datetime.datetime.now(datetime.UTC)
    previous_hour = now.replace(minute=0, second=0, microsecond=0) - datetime.timedelta(hours=1)
    target_hour = previous_hour.isoformat()

    return {
        "ops": {
            "ingest_event_properties": {"config": {"target_hour": target_hour}},
            "ingest_person_properties": {"config": {"target_hour": target_hour}},
        }
    }


# Add a config for running a backfill for a specific day
def run_backfill_for_day(date_str: str):
    """
    Helper function to create a run config for a backfill for a specific day.

    Args:
        date_str: Date string in YYYY-MM-DD format

    Returns:
        Dagster run config for the backfill
    """
    start_date = f"{date_str} 00:00:00"
    end_date = f"{date_str} 23:59:59"

    return {
        "ops": {
            "ingest_event_properties": {"config": {"start_date": start_date, "end_date": end_date}},
            "ingest_person_properties": {"config": {"start_date": start_date, "end_date": end_date}},
        }
    }


# Helper to run backfill for a specific hour
def run_backfill_for_hour(hour_str: str):
    """
    Helper function to create a run config for a backfill for a specific hour.

    Args:
        hour_str: ISO format datetime string for the hour (e.g., "2023-05-15T14:00:00+00:00")

    Returns:
        Dagster run config for the backfill
    """
    return {
        "ops": {
            "ingest_event_properties": {"config": {"target_hour": hour_str}},
            "ingest_person_properties": {"config": {"target_hour": hour_str}},
        }
    }
