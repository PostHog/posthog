import collections.abc
import csv
import datetime as dt
import json
import tempfile
import typing
from string import Template

from temporalio import workflow

SELECT_QUERY_TEMPLATE = Template(
    """
    SELECT $fields
    FROM events
    WHERE
        -- These 'timestamp' checks are a heuristic to exploit the sort key.
        -- Ideally, we need a schema that serves our needs, i.e. with a sort key on the _timestamp field used for batch exports.
        -- As a side-effect, this heuristic will discard historical loads older than 2 days.
        timestamp >= toDateTime64({data_interval_start}, 6, 'UTC') - INTERVAL 2 DAY
        AND timestamp < toDateTime64({data_interval_end}, 6, 'UTC') + INTERVAL 1 DAY
        AND COALESCE(inserted_at, _timestamp) >= toDateTime64({data_interval_start}, 6, 'UTC')
        AND COALESCE(inserted_at, _timestamp) < toDateTime64({data_interval_end}, 6, 'UTC')
        AND team_id = {team_id}
    $order_by
    $format
    """
)


async def get_rows_count(client, team_id: int, interval_start: str, interval_end: str) -> int:
    data_interval_start_ch = dt.datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = dt.datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")
    query = SELECT_QUERY_TEMPLATE.substitute(
        fields="count(DISTINCT event, cityHash64(distinct_id), cityHash64(uuid)) as count", order_by="", format=""
    )

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


FIELDS = """
DISTINCT ON (event, cityHash64(distinct_id), cityHash64(uuid))
toString(uuid) as uuid,
team_id,
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
"""


def get_results_iterator(
    client, team_id: int, interval_start: str, interval_end: str, legacy: bool = False
) -> typing.Generator[dict[str, typing.Any], None, None]:
    data_interval_start_ch = dt.datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = dt.datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")
    query = SELECT_QUERY_TEMPLATE.substitute(
        fields=FIELDS,
        order_by="ORDER BY inserted_at",
        format="FORMAT ArrowStream",
    )

    for batch in client.stream_query_as_arrow(
        query,
        query_parameters={
            "team_id": team_id,
            "data_interval_start": data_interval_start_ch,
            "data_interval_end": data_interval_end_ch,
        },
    ):
        yield from iter_batch_records(batch)


def iter_batch_records(batch) -> typing.Generator[dict[str, typing.Any], None, None]:
    """Iterate over records of a batch.

    During iteration, we yield dictionaries with all fields used by PostHog BatchExports.

    Args:
        batch: A record batch of rows.
    """
    for record in batch.to_pylist():
        properties = record.get("properties")
        person_properties = record.get("person_properties")
        properties = json.loads(properties) if properties else None

        # This is not backwards compatible, as elements should contain a parsed array.
        # However, parsing elements_chain is a mess, so we json.dump to at least be compatible with
        # schemas that use JSON-like types.
        elements = json.dumps(record.get("elements_chain").decode())

        record = {
            "created_at": record.get("created_at").strftime("%Y-%m-%d %H:%M:%S.%f"),
            "distinct_id": record.get("distinct_id").decode(),
            "elements": elements,
            "elements_chain": record.get("elements_chain").decode(),
            "event": record.get("event").decode(),
            "inserted_at": record.get("inserted_at").strftime("%Y-%m-%d %H:%M:%S.%f")
            if record.get("inserted_at")
            else None,
            "ip": properties.get("$ip", None) if properties else None,
            "person_id": record.get("person_id").decode(),
            "person_properties": json.loads(person_properties) if person_properties else None,
            "set": properties.get("$set", None) if properties else None,
            "set_once": properties.get("$set_once", None) if properties else None,
            "properties": properties,
            "site_url": properties.get("$current_url", None) if properties else None,
            "team_id": record.get("team_id"),
            "timestamp": record.get("timestamp").strftime("%Y-%m-%d %H:%M:%S.%f"),
            "uuid": record.get("uuid").decode(),
        }

        yield record


def get_data_interval(interval: str, data_interval_end: str | None) -> tuple[dt.datetime, dt.datetime]:
    """Return the start and end of an export's data interval.

    Args:
        interval: The interval of the BatchExport associated with this Workflow.
        data_interval_end: The optional end of the BatchExport period. If not included, we will
            attempt to extract it from Temporal SearchAttributes.

    Raises:
        TypeError: If when trying to obtain the data interval end we run into non-str types.
        ValueError: If passing an unsupported interval value.

    Returns:
        A tuple of two dt.datetime indicating start and end of the data_interval.
    """
    data_interval_end_str = data_interval_end

    if not data_interval_end_str:
        data_interval_end_search_attr = workflow.info().search_attributes.get("TemporalScheduledStartTime")

        # These two if-checks are a bit pedantic, but Temporal SDK is heavily typed.
        # So, they exist to make mypy happy.
        if data_interval_end_search_attr is None:
            msg = (
                "Expected 'TemporalScheduledStartTime' of type 'list[str]' or 'list[datetime], found 'NoneType'."
                "This should be set by the Temporal Schedule unless triggering workflow manually."
                "In the latter case, ensure 'S3BatchExportInputs.data_interval_end' is set."
            )
            raise TypeError(msg)

        # Failing here would perhaps be a bug in Temporal.
        if isinstance(data_interval_end_search_attr[0], str):
            data_interval_end_str = data_interval_end_search_attr[0]
            data_interval_end_dt = dt.datetime.fromisoformat(data_interval_end_str)

        elif isinstance(data_interval_end_search_attr[0], dt.datetime):
            data_interval_end_dt = data_interval_end_search_attr[0]

        else:
            msg = (
                f"Expected search attribute to be of type 'str' or 'datetime' found '{data_interval_end_search_attr[0]}' "
                f"of type '{type(data_interval_end_search_attr[0])}'."
            )
            raise TypeError(msg)
    else:
        data_interval_end_dt = dt.datetime.fromisoformat(data_interval_end_str)

    if interval == "hour":
        data_interval_start_dt = data_interval_end_dt - dt.timedelta(hours=1)
    elif interval == "day":
        data_interval_start_dt = data_interval_end_dt - dt.timedelta(days=1)
    else:
        raise ValueError(f"Unsupported interval: '{interval}'")

    return (data_interval_start_dt, data_interval_end_dt)


def json_dumps_bytes(d, encoding="utf-8") -> bytes:
    return json.dumps(d).encode(encoding)


class BatchExportTemporaryFile:
    """A TemporaryFile used to as an intermediate step while exporting data.

    This class does not implement the file-like interface but rather passes any calls
    to the underlying tempfile.NamedTemporaryFile. We do override 'write' methods
    to allow tracking bytes and records.
    """

    def __init__(
        self,
        mode: str = "w+b",
        buffering=-1,
        encoding: str | None = None,
        newline: str | None = None,
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | None = None,
        *,
        errors: str | None = None,
    ):
        self._file = tempfile.NamedTemporaryFile(
            mode=mode,
            encoding=encoding,
            newline=newline,
            buffering=buffering,
            suffix=suffix,
            prefix=prefix,
            dir=dir,
            errors=errors,
        )
        self.bytes_total = 0
        self.records_total = 0
        self.bytes_since_last_reset = 0
        self.records_since_last_reset = 0

    def __getattr__(self, name):
        """Pass get attr to underlying tempfile.NamedTemporaryFile."""
        return self._file.__getattr__(name)

    def __enter__(self):
        """Context-manager protocol enter method."""
        self._file.__enter__()
        return self

    def __exit__(self, exc, value, tb):
        """Context-manager protocol exit method."""
        return self._file.__exit__(exc, value, tb)

    def write(self, content: bytes | str):
        """Write bytes to underlying file keeping track of how many bytes were written."""
        if "b" in self.mode and isinstance(content, str):
            content = content.encode("utf-8")
        result = self._file.write(content)

        self.bytes_total += result
        self.bytes_since_last_reset += result

        return result

    def write_records_to_jsonl(self, records):
        """Write records to a temporary file as JSONL."""
        jsonl_dump = b"\n".join(map(json_dumps_bytes, records))

        if len(records) == 1:
            jsonl_dump += b"\n"

        result = self.write(jsonl_dump)

        self.records_total += len(records)
        self.records_since_last_reset += len(records)

        return result

    def write_records_to_csv(
        self,
        records,
        fieldnames: None | collections.abc.Sequence[str] = None,
        extrasaction: typing.Literal["raise", "ignore"] = "ignore",
        delimiter: str = ",",
        quotechar: str = '"',
        escapechar: str = "\\",
        quoting=csv.QUOTE_NONE,
    ):
        """Write records to a temporary file as CSV."""
        if len(records) == 0:
            return

        if fieldnames is None:
            fieldnames = list(records[0].keys())

        writer = csv.DictWriter(
            self,
            fieldnames=fieldnames,
            extrasaction=extrasaction,
            delimiter=delimiter,
            quotechar=quotechar,
            escapechar=escapechar,
            quoting=quoting,
        )
        writer.writerows(records)

        self.records_total += len(records)
        self.records_since_last_reset += len(records)

    def write_records_to_tsv(
        self,
        records,
        fieldnames: None | list[str] = None,
        extrasaction: typing.Literal["raise", "ignore"] = "ignore",
        quotechar: str = '"',
        escapechar: str = "\\",
        quoting=csv.QUOTE_NONE,
    ):
        """Write records to a temporary file as TSV."""
        return self.write_records_to_csv(
            records,
            fieldnames=fieldnames,
            extrasaction=extrasaction,
            delimiter="\t",
            quotechar=quotechar,
            escapechar=escapechar,
            quoting=quoting,
        )

    def reset(self):
        """Reset underlying file by truncating it.

        Also resets the tracker attributes for bytes and records since last reset.
        """
        self._file.seek(0)
        self._file.truncate()

        self.bytes_since_last_reset = 0
        self.records_since_last_reset = 0
