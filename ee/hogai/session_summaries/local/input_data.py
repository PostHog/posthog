import os
import re
import datetime
from contextlib import contextmanager
from typing import Any, Optional

import pytz
from clickhouse_driver import Client

from posthog.session_recordings.models.metadata import RecordingMetadata
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents


def _get_ch_client_local_reads_prod() -> Client:
    return Client(
        host=os.environ["LOCAL_READS_PROD_CLICKHOUSE_US_HOST"],
        user=os.environ["LOCAL_READS_PROD_CLICKHOUSE_US_USER"],
        password=os.environ["LOCAL_READS_PROD_CLICKHOUSE_US_PASSWORD"],
        secure=True,
        verify=False,
    )


@contextmanager
def _ch_client_local_reads_prod():
    client = _get_ch_client_local_reads_prod()
    try:
        yield client
    finally:
        client.disconnect()


def _get_production_session_metadata_locally(
    events_obj: SessionReplayEvents,
    session_id: str,
    team_id: int,
    recording_start_time: Optional[datetime.datetime] = None,
) -> RecordingMetadata | None:
    query = events_obj.get_metadata_query(recording_start_time)
    with _ch_client_local_reads_prod() as client:
        replay_response = client.execute(
            query,
            {
                "team_id": team_id,
                "session_id": session_id,
                "recording_start_time": recording_start_time,
                "python_now": datetime.datetime.now(pytz.timezone("UTC")),
            },
        )
    recording_metadata = events_obj.build_recording_metadata(session_id, replay_response)
    return recording_metadata


def _interpolate_events_query(events_query: str, events_values: dict[str, Any] | None) -> str:
    """
    Interpolate events query to get valid CH query.
    """

    def _format_value(v):
        if isinstance(v, str):
            safe_v = v.replace("'", "''")
            return f"'{safe_v}'"
        elif isinstance(v, datetime.datetime):
            # Converting into Unix timestamp to avoid timezone issues
            return str(int(v.astimezone(datetime.UTC).timestamp()))
        elif isinstance(v, list):
            # ClickHouse expects arrays as (val1, val2, ...)
            return "(" + ", ".join(_format_value(x) for x in v) + ")"
        elif v is None:
            return "NULL"
        else:
            return str(v)

    if not events_values:
        return events_query
    return events_query.format(**{k: _format_value(v) for k, v in events_values.items()})


def _rewrite_properties_fields(query: str) -> str:
    """
    Rewrite properties.$field format to extract string from JSON.
    """

    def _replacer(match):
        field = match.group(1)
        return f"JSONExtractString(properties, '${field}') AS {field}"

    select_match = re.search(r"SELECT\s+(.*?)\s+FROM", query, re.DOTALL | re.IGNORECASE)
    if not select_match:
        return query
    select_clause = select_match.group(1)
    new_select = re.sub(r"properties\.\$([a-zA-Z0-9_]+)", _replacer, select_clause)
    return query.replace(select_clause, new_select, 1)


def _get_production_session_events_locally(
    events_obj: SessionReplayEvents,
    session_id: str,
    metadata: RecordingMetadata,
    limit: int,
    page: int,
    events_to_ignore: list[str] | None = None,
    extra_fields: list[str] | None = None,
) -> tuple[list | None, list | None]:
    """
    Get session events from production, locally, required for testing session summary
    """
    hq = events_obj.get_events_query(
        session_id=session_id,
        metadata=metadata,
        events_to_ignore=events_to_ignore,
        extra_fields=extra_fields,
        limit=limit,
        page=page,
    )
    query = _rewrite_properties_fields(hq.query)
    interpolated_query = _interpolate_events_query(query, hq.values)
    with _ch_client_local_reads_prod() as client:
        rows, columns_with_types = client.execute(interpolated_query, with_column_types=True)
    columns = [col for col, _ in columns_with_types]
    return columns, rows
