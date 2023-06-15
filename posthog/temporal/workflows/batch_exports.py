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
        raise ValueError(f"Unexpected result from ClickHouse: {row}")

    return row["count"]


def get_results_iterator(client: ChClient, team_id: int, interval_start: str, interval_end: str):
    data_interval_start_ch = datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")

    return client.iterate(
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
    )
