import json
import tempfile
from datetime import datetime
from string import Template

from aiochclient import ChClient

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
    $order_by
    """
)


async def get_rows_count(client: ChClient, team_id: int, interval_start: str, interval_end: str) -> int:
    data_interval_start_ch = datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")

    row = await client.fetchrow(
        SELECT_QUERY_TEMPLATE.substitute(fields="count(*) as count", order_by=""),
        params={
            "team_id": team_id,
            "data_interval_start": data_interval_start_ch,
            "data_interval_end": data_interval_end_ch,
        },
    )

    if row is None:
        raise ValueError("Unexpected result from ClickHouse: `None` returned for count query")

    return sum(int(row["count"]) for row in row)


async def get_results_iterator(client: ChClient, team_id: int, interval_start: str, interval_end: str):
    data_interval_start_ch = datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")

    async for row in client.iterate(
        SELECT_QUERY_TEMPLATE.safe_substitute(
            fields="""
                    uuid,
                    timestamp,
                    _timestamp,
                    created_at,
                    event,
                    properties,
                    -- Point in time identity fields
                    distinct_id,
                    person_id,
                    person_properties,
                    -- Autocapture fields
                    elements_chain
            """,
            order_by="ORDER BY _timestamp",
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


def json_dumps_bytes(d, encoding="utf-8") -> bytes:
    return json.dumps(d).encode(encoding)


class BatchExportTemporaryFile:
    def __init__(self, *args, **kwargs):
        self.named_temp_file = tempfile.NamedTemporaryFile(*args, **kwargs)
        self.bytes_total = 0
        self.records_total = 0
        self.bytes_since_last_reset = 0
        self.records_since_last_reset = 0

    def __getattr__(self, name):
        return self.named_temp_file.__getattr__(name)

    def __enter__(self):
        self.named_temp_file.__enter__()
        return self

    def __exit__(self, exc, value, tb):
        return self.named_temp_file.__exit__(exc, value, tb)

    def write(self, b):
        self.bytes_total += len(b)
        self.bytes_since_last_reset += len(b)

        return self.named_temp_file.write(b)

    def write_records_to_jsonl(self, records):
        self.records_total += len(records)
        self.records_since_last_reset += len(records)

        jsonl_dump = b"\n".join(map(json_dumps_bytes, records))

        if len(records) == 1:
            jsonl_dump += b"\n"

        self.write(jsonl_dump)

    def reset(self):
        self.named_temp_file.seek(0)
        self.named_temp_file.truncate()
        self.bytes_written_since_last_reset = 0
        self.records_since_last_reset = 0
