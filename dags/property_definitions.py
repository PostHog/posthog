import datetime
from dataclasses import dataclass

import dagster
import pydantic

from posthog.clickhouse.cluster import ClickhouseCluster, Query
from posthog.models.property_definition import PropertyDefinition

from dags.common import JobOwners


@dataclass(frozen=True)
class TimeRange:
    start_time: datetime
    end_time: datetime

    def get_expression(self, column: str) -> str:
        return f"{column} >= '{self.start_time.isoformat()}' AND {column} < '{self.end_time.isoformat()}'"


class PropertyDefinitionsConfig(dagster.Config):
    """Configuration for property definitions ingestion job."""

    start_at: str = pydantic.Field(
        description="The lower bound (inclusive) timestamp to be used when selecting rows to be included within the "
        "ingestion window. The value can be provided in any format that can be parsed by ClickHouse best-effort date "
        "parsing."
    )
    duration: str = pydantic.Field(
        description="The size of the ingestion window, used to determine the upper bound (non-inclusive) of the time "
        "range. The value can be provided in any format that can be parsed as a ClickHouse interval.",
        default="1 hour",
    )

    def validate(self, cluster: ClickhouseCluster) -> TimeRange:
        """Validate the configuration values, returning a time range."""
        [[start_time, end_time]] = cluster.any_host(
            Query(
                f"SELECT parseDateTimeBestEffort(%(start_at)s) as start_time, start_time + INTERVAL %(duration)s",
                {"start_at": self.start_at, "duration": self.duration},
            )
        ).result()
        return TimeRange(start_time, end_time)


@dagster.op
def setup_job(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: PropertyDefinitionsConfig,
) -> TimeRange:
    """Validates the job configuration to be provided to other ops."""
    return config.validate(cluster)


@dataclass(frozen=True)
class DetectPropertyTypeExpression:
    source_column: str

    def __str__(self) -> str:
        # largely derived from https://github.com/PostHog/posthog/blob/052f4ea40c5043909115f835f09445e18dd9727c/rust/property-defs-rs/src/types.rs#L314-L373
        return f"""
            arrayMap(
                (name, value) -> (name, multiIf(
                    -- special cases: key patterns
                    name ilike 'utm_%', 'String',
                    name ilike '$feature/%', 'String',
                    name ilike '$feature_flag_response', 'String',
                    name ilike '$survey_response%', 'String',
                    -- special cases: timestamp detection
                    (
                        multiSearchAnyCaseInsensitive(name, ['time', 'timestamp', 'date', '_at', '-at', 'createdat', 'updatedat'])
                        AND JSONType(value) IN ('Int64', 'UInt64', 'Double')
                        AND JSONExtract(value, 'Nullable(Float)') >= toUnixTimestamp(now() - interval '6 months')
                    ), 'DateTime',
                    -- special cases: string value patterns
                    (
                        JSONType(value) = 'String'
                        AND trimBoth(JSONExtractString(value)) IN ('true', 'TRUE', 'false', 'FALSE')
                    ), 'Boolean',
                    (
                        JSONType(value) = 'String'
                        AND length(trimBoth(JSONExtractString(value)) as trimmed_value) >= 10  -- require at least a date part
                        AND parseDateTime64BestEffortOrNull(trimmed_value) IS NOT NULL  -- can be parsed as a date
                        AND JSONExtract(trimmed_value, 'Nullable(Float)') IS NULL  -- but not as a timestamp
                    ), 'DateTime',
                    -- primitive types
                    JSONType(value) = 'Bool', 'Boolean',
                    JSONType(value) = 'String', 'String',
                    JSONType(value) IN ('Int64', 'UInt64', 'Double'), 'Numeric',
                    NULL
                )),
                arrayFilter(
                    (name, value) -> (
                        -- https://github.com/PostHog/posthog/blob/052f4ea40c5043909115f835f09445e18dd9727c/rust/property-defs-rs/src/types.rs#L17-L28
                        name NOT IN ('$set', '$set_once', '$unset', '$group_0', '$group_1', '$group_2', '$group_3', '$group_4', '$groups')
                        -- https://github.com/PostHog/posthog/blob/052f4ea40c5043909115f835f09445e18dd9727c/rust/property-defs-rs/src/types.rs#L279-L286
                        AND length(name) <= 200
                    ),
                    JSONExtractKeysAndValuesRaw({self.source_column})
                )
            )
        """


@dagster.op
def ingest_event_properties(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    time_range: TimeRange,
) -> int:
    """
    Ingest event properties from events_recent table into property_definitions table.
    """
    # Log the execution parameters
    context.log.info(f"Ingesting event properties for {time_range!r}")

    # Query to insert event properties into property_definitions table
    insert_query = f"""
    INSERT INTO property_definitions
    SELECT
        team_id,
        team_id as project_id,
        (arrayJoin({DetectPropertyTypeExpression('properties')}) as property).1 as name,
        property.2 as property_type,
        replaceAll(event, '\\0', '\ufffd') as event,  -- https://github.com/PostHog/posthog/blob/052f4ea40c5043909115f835f09445e18dd9727c/rust/property-defs-rs/src/types.rs#L172
        NULL as group_type_index,
        {int(PropertyDefinition.Type.EVENT)} as type,
        -- NOTE: not floored, need to check if needed https://github.com/PostHog/posthog/blob/052f4ea40c5043909115f835f09445e18dd9727c/rust/property-defs-rs/src/types.rs#L175
        max(timestamp) as last_seen_at
    FROM events_recent
    WHERE
        {time_range.get_expression("timestamp")}
        -- https://github.com/PostHog/posthog/blob/052f4ea40c5043909115f835f09445e18dd9727c/rust/property-defs-rs/src/types.rs#L13-L14C52
        AND event NOT IN ('$$plugin_metrics')
        -- https://github.com/PostHog/posthog/blob/052f4ea40c5043909115f835f09445e18dd9727c/rust/property-defs-rs/src/types.rs#L187-L191
        AND length(event) <= 200
    GROUP BY team_id, event, name, property_type
    ORDER BY team_id, event, name, property_type NULLS LAST
    LIMIT 1 by team_id, event, name
    """

    context.log.info("Executing insert query...")
    cluster.any_host(Query(insert_query)).result()

    # Get the number of rows inserted for this specific time window
    count_query = f"""
    SELECT count() FROM property_definitions
    WHERE
        type = {int(PropertyDefinition.Type.EVENT)}
        AND {time_range.get_expression("last_seen_at")}
    """

    rows = cluster.any_host(Query(count_query)).result()[0][0]
    context.log.info(f"Inserted {rows} event property definitions")

    return rows


@dagster.op
def ingest_person_properties(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    time_range: TimeRange,
) -> int:
    """
    Ingest person properties from person table into property_definitions table.
    """
    # Log the execution parameters
    context.log.info(f"Ingesting person properties for {time_range!r}")

    # Query to insert person properties into property_definitions table
    # NOTE: this is a different data source from current, see https://github.com/PostHog/product-internal/pull/748/files#diff-78e7399938cb790eae10d5c5769f7edcb531972f33a32e0655872bded13f4977R165-R170
    insert_query = f"""
    INSERT INTO property_definitions
    SELECT
        team_id,
        team_id as project_id,
        (arrayJoin({DetectPropertyTypeExpression('properties')}) as property).1 as name,
        property.2 as property_type,
        NULL as event,
        NULL as group_type_index,
        {int(PropertyDefinition.Type.PERSON)} as type,
        max(_timestamp) as last_seen_at
    FROM person
    WHERE
        {time_range.get_expression("_timestamp")}
    GROUP BY team_id, name, property_type
    ORDER BY team_id, name, property_type NULLS LAST
    LIMIT 1 by team_id, name
    """

    context.log.info("Executing insert query...")
    cluster.any_host(Query(insert_query)).result()

    # Get the number of rows inserted for this specific time window
    count_query = f"""
    SELECT count() FROM property_definitions
    WHERE
        type = {int(PropertyDefinition.Type.PERSON)}
        AND {time_range.get_expression("last_seen_at")}
    """

    rows = cluster.any_host(Query(count_query)).result()[0][0]
    context.log.info(f"Inserted {rows} person property definitions")

    return rows


@dagster.op
def ingest_group_properties(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    time_range: TimeRange,
) -> int:
    """
    Ingest group properties from group table into property_definitions table.
    """
    # Log the execution parameters
    context.log.info(f"Ingesting group properties for {time_range!r}")

    # Query to insert group properties into property_definitions table
    # NOTE: this is a different data source from current, see https://github.com/PostHog/product-internal/pull/748/files#diff-78e7399938cb790eae10d5c5769f7edcb531972f33a32e0655872bded13f4977R165-R170
    insert_query = f"""
    INSERT INTO property_definitions
    SELECT
        team_id,
        team_id as project_id,
        (arrayJoin({DetectPropertyTypeExpression('group_properties')}) as property).1 as name,
        property.2 as property_type,
        NULL as event,
        group_type_index,
        {int(PropertyDefinition.Type.GROUP)} as type,
        max(_timestamp) as last_seen_at
    FROM groups
    WHERE
        {time_range.get_expression("_timestamp")}
    GROUP BY team_id, name, property_type, group_type_index
    ORDER BY team_id, name, property_type NULLS LAST, group_type_index
    LIMIT 1 by team_id, name, group_type_index
    """

    context.log.info("Executing insert query...")
    cluster.any_host(Query(insert_query)).result()

    # Get the number of rows inserted for this specific time window
    count_query = f"""
    SELECT count() FROM property_definitions
    WHERE
        type = {int(PropertyDefinition.Type.GROUP)}
        AND {time_range.get_expression("last_seen_at")}
    """

    rows = cluster.any_host(Query(count_query)).result()[0][0]
    context.log.info(f"Inserted {rows} group property definitions")

    return rows


@dagster.op
def optimize_property_definitions(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    time_range: TimeRange,
    event_count: int,
    person_count: int,
    group_count: int,
) -> int:
    """
    Run OPTIMIZE on property_definitions table to deduplicate inserted data.

    This runs after both event and person property ingestion completes successfully.
    """
    context.log.info(
        f"Running OPTIMIZE TABLE for {event_count} event properties, {person_count} person properties, {group_count} group properties"
    )

    # Run OPTIMIZE after all inserts to merge duplicates using the ReplacingMergeTree's version column
    cluster.any_host(Query("OPTIMIZE TABLE property_definitions FINAL")).result()

    # Get the total number of property definitions for this time window
    count_query = f"""
    SELECT count() FROM property_definitions
    WHERE {time_range.get_expression("last_seen_at")}
    """

    total = cluster.any_host(Query(count_query)).result()[0][0]
    context.log.info(f"Total property definitions after optimization: {total}")

    return total


@dagster.job(
    name="property_definitions_ingestion",
    tags={
        "owner": JobOwners.TEAM_CLICKHOUSE.value,
        "disable_slack_notifications": True,  # NOTE: remove when enabled for production use
    },
)
def property_definitions_ingestion_job():
    """
    Job that ingests properties into the property_definitions table.

    This job runs in the following sequence:
    1. Ingest event properties
    2. Ingest person properties
    3. Ingest group properties
    4. Run OPTIMIZE FINAL on the table
    """
    time_range = setup_job()
    event_count = ingest_event_properties(time_range)
    person_count = ingest_person_properties(time_range)
    group_count = ingest_group_properties(time_range)
    optimize_property_definitions(time_range, event_count, person_count, group_count)


@dagster.schedule(
    job=property_definitions_ingestion_job,
    cron_schedule="5 * * * *",  # Run 5 minutes after the hour
    execution_timezone="UTC",
)
def property_definitions_hourly_schedule():
    """
    Schedule the property definitions ingestion job to run hourly.

    Runs 5 minutes after each hour to process data from the previous hour.
    """
    # Calculate the previous hour in ISO format
    now = datetime.datetime.now(datetime.UTC)
    previous_hour = now.replace(minute=0, second=0, microsecond=0) - datetime.timedelta(hours=1)
    target_hour = previous_hour.isoformat()
    return dagster.RunRequest(
        run_key=target_hour,
        run_config={
            "ops": {
                setup_job.name: {
                    "config": PropertyDefinitionsConfig(start_at=target_hour, duration="1 hour").model_dump()
                }
            }
        },
    )
