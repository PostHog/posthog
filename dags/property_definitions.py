import datetime
from typing import Optional

import dagster
from dagster import schedule, job, Config

from dags.common import JobOwners
from posthog.clickhouse.cluster import ClickhouseCluster, Query


class PropertyDefinitionsConfig(Config):
    """Configuration for property definitions ingestion job."""

    # Process a specific hour (ISO format) instead of lookback
    target_hour: Optional[str] = None
    # For backfill runs, we can specify a start and end date
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    def get_time_filter_expression(self, column: str) -> str:
        if self.start_date and self.end_date:
            # For backfill runs - these should already be in the right format
            return f"{column} BETWEEN toDateTime('{self.start_date}') AND toDateTime('{self.end_date}')"
        elif self.target_hour:
            # For processing a specific complete hour
            hour_start = datetime.datetime.fromisoformat(self.target_hour)
            hour_end = hour_start + datetime.timedelta(hours=1)
            start_formatted = format_datetime_for_clickhouse(hour_start)
            end_formatted = format_datetime_for_clickhouse(hour_end)
            return f"{column} BETWEEN toDateTime('{start_formatted}') AND toDateTime('{end_formatted}')"
        else:
            # Default to previous complete hour
            now = datetime.datetime.now(datetime.UTC)
            previous_hour = now.replace(minute=0, second=0, microsecond=0) - datetime.timedelta(hours=1)
            hour_end = previous_hour + datetime.timedelta(hours=1)
            start_formatted = format_datetime_for_clickhouse(previous_hour)
            end_formatted = format_datetime_for_clickhouse(hour_end)
            return f"{column} BETWEEN toDateTime('{start_formatted}') AND toDateTime('{end_formatted}')"


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


@dagster.op
def ingest_event_properties(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: PropertyDefinitionsConfig,
) -> int:
    """
    Ingest event properties from events_recent table into property_definitions table.

    Uses the JSONExtractKeysAndValuesRaw function to extract property keys and values,
    then determines the property type using JSONType.
    """
    time_filter = config.get_time_filter_expression("timestamp")

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
    """

    context.log.info("Executing insert query...")
    cluster.any_host(Query(query)).result()

    # Get the number of rows inserted for this specific time window
    count_query = f"""
    SELECT count() FROM property_definitions
    WHERE type = 1 AND {config.get_time_filter_expression("last_seen_at")}
    """

    rows = cluster.any_host(Query(count_query)).result()[0][0]
    context.log.info(f"Inserted {rows} event property definitions")

    return rows


@dagster.op
def ingest_person_properties(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: PropertyDefinitionsConfig,
) -> int:
    """
    Ingest person properties from person table into property_definitions table.

    Uses the JSONExtractKeysAndValuesRaw function to extract property keys and values,
    then determines the property type using JSONType.
    """
    time_filter = config.get_time_filter_expression("_timestamp")

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
    """

    context.log.info("Executing insert query...")
    cluster.any_host(Query(query)).result()

    # Get the number of rows inserted for this specific time window
    count_query = f"""
    SELECT count() FROM property_definitions
    WHERE type = 2 AND {config.get_time_filter_expression("last_seen_at")}
    """

    rows = cluster.any_host(Query(count_query)).result()[0][0]
    context.log.info(f"Inserted {rows} person property definitions")

    return rows


@dagster.op
def optimize_property_definitions(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: PropertyDefinitionsConfig,
    event_count: int,
    person_count: int,
) -> int:
    """
    Run OPTIMIZE on property_definitions table to deduplicate inserted data.

    This runs after both event and person property ingestion completes successfully.
    """
    context.log.info(f"Running OPTIMIZE TABLE for {event_count} event properties and {person_count} person properties")

    # Run OPTIMIZE after all inserts to merge duplicates using the ReplacingMergeTree's version column
    cluster.any_host(Query("OPTIMIZE TABLE property_definitions FINAL")).result()

    # Get the total number of property definitions for this time window
    count_query = f"""
    SELECT count() FROM property_definitions
    WHERE {config.get_time_filter_expression("last_seen_at")}
    """

    total = cluster.any_host(Query(count_query)).result()[0][0]
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
    event_count = ingest_event_properties()
    person_count = ingest_person_properties()
    optimize_property_definitions(event_count, person_count)


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
            "optimize_property_definitions": {"config": {"target_hour": target_hour}},
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
