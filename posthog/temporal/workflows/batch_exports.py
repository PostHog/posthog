import json
from datetime import datetime
from string import Template

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
        AND COALESCE(inserted_at, _timestamp) >= toDateTime64({data_interval_start}, 6, 'UTC')
        AND COALESCE(inserted_at, _timestamp) < toDateTime64({data_interval_end}, 6, 'UTC')
        AND team_id = {team_id}
    $order_by
    $format
    """
)


async def get_rows_count(client, team_id: int, interval_start: str, interval_end: str):
    data_interval_start_ch = datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")
    query = SELECT_QUERY_TEMPLATE.substitute(fields="count(*) as count", order_by="", format="")
    count = await client.read_query(
        query,
        query_parameters={
            "team_id": team_id,
            "data_interval_start": data_interval_start_ch,
            "data_interval_end": data_interval_end_ch,
        },
    )

    if count is None or len(count) == 0:
        raise ValueError("Unexpected result from ClickHouse: `None` returned for count query")

    return int(count)


async def get_results_iterator(client, team_id: int, interval_start: str, interval_end: str):
    data_interval_start_ch = datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")
    query = SELECT_QUERY_TEMPLATE.substitute(
        fields="""
                    toString(uuid) as uuid,
                    timestamp,
                    inserted_at,
                    created_at,
                    event,
                    properties,
                    -- Point in time identity fields
                    toString(distinct_id) as distinct_id,
                    toString(person_id) as person_id,
                    person_properties,
                    -- Autocapture fields
                    elements_chain
            """,
        order_by="ORDER BY _timestamp",
        format="FORMAT ArrowStream",
    )

    async for batch in client.stream_query_as_arrow(
        query,
        query_parameters={
            "team_id": team_id,
            "data_interval_start": data_interval_start_ch,
            "data_interval_end": data_interval_end_ch,
        },
    ):
        # Make sure to parse `properties` and
        # `person_properties` are parsed as JSON to `dict`s. In ClickHouse they
        # are stored as `String`s.
        for row in batch.to_pylist():
            properties = row.get("properties")
            person_properties = row.get("person_properties")

            yield {
                "uuid": row.get("uuid").decode(),
                "distinct_id": row.get("distinct_id").decode(),
                "person_id": row.get("person_id").decode(),
                "event": row.get("event").decode(),
                "_timestamp": datetime.fromtimestamp(row.get("_timestamp")).strftime("%Y-%m-%d %H:%M:%S"),
                "created_at": row.get("created_at").strftime("%Y-%m-%d %H:%M:%S.%f"),
                "timestamp": row.get("timestamp").strftime("%Y-%m-%d %H:%M:%S.%f"),
                "properties": json.loads(properties) if properties else None,
                "person_properties": json.loads(person_properties) if person_properties else None,
                "elements_chain": row.get("elements_chain").decode(),
            }
