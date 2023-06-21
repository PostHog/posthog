import json
from string import Template

from aiochclient import ChClient

from datetime import datetime


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


async def get_rows_count(client: ChClient, team_id: int, interval_start: str, interval_end: str):
    data_interval_start_ch = datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")

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


async def get_results_iterator(client: ChClient, team_id: int, interval_start: str, interval_end: str):
    data_interval_start_ch = datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")

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
