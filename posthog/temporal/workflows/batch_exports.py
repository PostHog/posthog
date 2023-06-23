import json
from string import Template

from aiochclient import ChClient

from datetime import datetime, timedelta

from temporalio import workflow


SELECT_QUERY_TEMPLATE = Template(
    """
    SELECT $fields
    FROM events
    WHERE
        -- These 'timestamp' checks are a heuristic to exploit the sort key.
        -- Ideally, we need a schema that serves our needs, i.e. with a sort key on the _timestamp field used for batch exports.
        -- As a side-effect, this heuristic will discard historical loads older than 2 days.
        timestamp >= toDateTime({data_interval_start}, 'UTC') - INTERVAL 2 DAY
        AND timestamp < toDateTime({data_interval_end}, 'UTC') + INTERVAL 1 DAY
        AND _timestamp >= toDateTime({data_interval_start}, 'UTC')
        AND _timestamp < toDateTime({data_interval_end}, 'UTC')
        AND team_id = {team_id}
    """
)


async def get_rows_count(client: ChClient, team_id: int, interval_start: datetime, interval_end: datetime):
    data_interval_start_ch = interval_start.strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = interval_end.strftime("%Y-%m-%d %H:%M:%S")

    row = await client.fetchrow(
        SELECT_QUERY_TEMPLATE.substitute(fields="count(*) as count"),
        params={
            "team_id": team_id,
            "data_interval_start": data_interval_start_ch,
            "data_interval_end": data_interval_end_ch,
        },
    )

    if row is None:
        raise ValueError("Unexpected result from ClickHouse: `None` returned for count query")

    return row["count"]


async def get_results_iterator(client: ChClient, team_id: int, interval_start: datetime, interval_end: datetime):
    data_interval_start_ch = interval_start.strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = interval_end.strftime("%Y-%m-%d %H:%M:%S")

    async for row in client.iterate(
        SELECT_QUERY_TEMPLATE.safe_substitute(
            fields="""
                    uuid,
                    timestamp,
                    created_at,
                    event,
                    properties,
                    -- Point in time identity fields
                    distinct_id,
                    person_id,
                    person_properties,
                    -- Autocapture fields
                    elements_chain
                """
        ),
        json=True,
        params={
            "team_id": team_id,
            "data_interval_start": data_interval_start_ch,
            "data_interval_end": data_interval_end_ch,
        },
    ):
        # Make sure to parse `properties` and
        # `person_properties` are parsed as JSON to `dict`s. In ClickHouse they
        # are stored as `String`s.
        properties = row.get("properties")
        person_properties = row.get("person_properties")
        yield {
            **row,
            "properties": json.loads(properties) if properties else None,
            "person_properties": json.loads(person_properties) if person_properties else None,
        }


def get_data_interval_from_workflow_inputs(interval: str, data_interval_end: datetime) -> tuple[datetime, datetime]:
    """
    Return the start and end of an export's data interval.

    If the data_interval_end_str is not provided, we try to obtain it from the
    temporal workflow's search attributes. If the workflow is started by a
    Temporal Schedule, this should be set by Temporal.

    NOTE: If we based the export on a data interval end provided by Temporal
    Schedule, we subtract 30 minutes from it to ensure we don't miss any data
    that might have been written to the database after the Temporal Schedule
    started the workflow. This isn't ideal and relies on the assumption that we
    will not lag behind in any part of the system by more than 30 minutes.

    Args:
        interval: The interval of the export, either 'hour' or 'day'.
        data_interval_start_str: The start of the data interval as a string.
        data_interval_end_str: The end of the data interval as a string.

    Raises:
        TypeError: If when trying to obtain the data interval end we run into non-str types.

    Returns:
        A tuple of two datetime indicating start and end of the data_interval.

    """
    data_interval_end = data_interval_end - timedelta(seconds=1800)

    if interval == "hour":
        data_interval_end = data_interval_end.replace(minute=0, second=0, microsecond=0)
        data_interval_start = data_interval_end - timedelta(hours=1)
    elif interval == "day":
        data_interval_end = data_interval_end.replace(hour=0, minute=0, second=0, microsecond=0)
        data_interval_start = data_interval_end - timedelta(days=1)
    else:
        raise ValueError(f"Unexpected interval: {interval}")

    return (data_interval_start, data_interval_end)


def get_workflow_scheduled_start_time(workflow_info: workflow.Info):
    """
    Given a Temporal workflow Info object, return the scheduled start time of
    the workflow. If the workflow was not started by a Temporal Schedule, this
    will be None.
    """
    scheduled_start_time = None
    workflow_schedule_time_attr = workflow_info.search_attributes.get("TemporalScheduledStartTime")
    if workflow_schedule_time_attr:
        # Failing here would perhaps be a bug in Temporal.
        if isinstance(workflow_schedule_time_attr[0], str):
            data_interval_end_str = workflow_schedule_time_attr[0]
            scheduled_start_time = data_interval_end_str

        elif isinstance(workflow_schedule_time_attr[0], datetime):
            scheduled_start_time = workflow_schedule_time_attr[0].isoformat()

        else:
            msg = (
                f"Expected search attribute to be of type 'str' or 'datetime' found '{workflow_schedule_time_attr[0]}' "
                f"of type '{type(workflow_schedule_time_attr[0])}'."
            )
            raise TypeError(msg)

    return scheduled_start_time
