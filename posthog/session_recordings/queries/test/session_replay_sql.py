from datetime import datetime
from typing import Optional, List, Dict
from uuid import uuid4

from dateutil.parser import parse
from dateutil.relativedelta import relativedelta

from posthog.clickhouse.log_entries import INSERT_LOG_ENTRY_SQL
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import (
    KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
    KAFKA_LOG_ENTRIES,
)
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.utils import cast_timestamp_or_now

INSERT_SINGLE_SESSION_REPLAY = """
INSERT INTO sharded_session_replay_events (
    session_id,
    team_id,
    distinct_id,
    min_first_timestamp,
    max_last_timestamp,
    first_url,
    click_count,
    keypress_count,
    mouse_activity_count,
    active_milliseconds,
    console_log_count,
    console_warn_count,
    console_error_count
)
SELECT
    %(session_id)s,
    %(team_id)s,
    %(distinct_id)s,
    toDateTime64(%(first_timestamp)s, 6, 'UTC'),
    toDateTime64(%(last_timestamp)s, 6, 'UTC'),
    argMinState(cast(%(first_url)s, 'Nullable(String)'), toDateTime64(%(first_timestamp)s, 6, 'UTC')),
    %(click_count)s,
    %(keypress_count)s,
    %(mouse_activity_count)s,
    %(active_milliseconds)s,
    %(console_log_count)s,
    %(console_warn_count)s,
    %(console_error_count)s
"""


def _sensible_first_timestamp(
    first_timestamp: Optional[str | datetime], last_timestamp: Optional[str | datetime]
) -> str:
    """
    Normalise the first timestamp to be used in the session replay summary.
    If it is not provided but there is a last_timestamp, use an hour before that last_timestamp
    Otherwise we use the current time
    """
    sensible_timestamp = None
    if first_timestamp is not None:
        # TRICKY: check it not a string to avoid needing to check if it is a datetime or a Fakedatetime
        if not isinstance(first_timestamp, str):
            sensible_timestamp = first_timestamp.isoformat()
        else:
            sensible_timestamp = first_timestamp
    else:
        if last_timestamp is not None:
            if isinstance(last_timestamp, str):
                last_timestamp = parse(last_timestamp)

            sensible_timestamp = (last_timestamp - relativedelta(seconds=3600)).isoformat()

    return format_clickhouse_timestamp(cast_timestamp_or_now(sensible_timestamp))


def _sensible_last_timestamp(
    first_timestamp: Optional[str | datetime], last_timestamp: Optional[str | datetime]
) -> str:
    """
    Normalise the last timestamp to be used in the session replay summary.
    If it is not provided but there is a first_timestamp, use an hour after that last_timestamp
    Otherwise we use the current time
    """
    sensible_timestamp = None
    if last_timestamp is not None:
        # TRICKY: check it not a string to avoid needing to check if it is a datetime or a Fakedatetime
        if not isinstance(last_timestamp, str):
            sensible_timestamp = last_timestamp.isoformat()
        else:
            sensible_timestamp = last_timestamp
    else:
        if first_timestamp is not None:
            if isinstance(first_timestamp, str):
                first_timestamp = parse(first_timestamp)

            sensible_timestamp = (first_timestamp - relativedelta(seconds=3600)).isoformat()

    return format_clickhouse_timestamp(cast_timestamp_or_now(sensible_timestamp))


def produce_replay_summary(
    team_id: int,
    session_id: Optional[str] = None,
    distinct_id: Optional[str] = None,
    first_timestamp: Optional[str | datetime] = None,
    last_timestamp: Optional[str | datetime] = None,
    first_url: Optional[str | None] = None,
    click_count: Optional[int] = None,
    keypress_count: Optional[int] = None,
    mouse_activity_count: Optional[int] = None,
    active_milliseconds: Optional[float] = None,
    console_log_count: Optional[int] = None,
    console_warn_count: Optional[int] = None,
    console_error_count: Optional[int] = None,
    log_messages: Dict[str, List[str]] | None = None,
):
    if log_messages is None:
        log_messages = {}

    first_timestamp = _sensible_first_timestamp(first_timestamp, last_timestamp)
    last_timestamp = _sensible_last_timestamp(first_timestamp, last_timestamp)

    timestamp = format_clickhouse_timestamp(cast_timestamp_or_now(first_timestamp))
    data = {
        "session_id": session_id or "1",
        "team_id": team_id,
        "distinct_id": distinct_id or "user",
        "first_timestamp": timestamp,
        "last_timestamp": format_clickhouse_timestamp(cast_timestamp_or_now(last_timestamp)),
        "first_url": first_url,
        "click_count": click_count or 0,
        "keypress_count": keypress_count or 0,
        "mouse_activity_count": mouse_activity_count or 0,
        "active_milliseconds": active_milliseconds or 0,
        "console_log_count": console_log_count or 0,
        "console_warn_count": console_warn_count or 0,
        "console_error_count": console_error_count or 0,
    }
    p = ClickhouseProducer()
    # because this is in a test it will write directly using SQL not really with Kafka
    p.produce(
        topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
        sql=INSERT_SINGLE_SESSION_REPLAY,
        data=data,
    )

    for level, messages in log_messages.items():
        for message in messages:
            p.produce(
                topic=KAFKA_LOG_ENTRIES,
                sql=INSERT_LOG_ENTRY_SQL,
                data={
                    "team_id": team_id,
                    "message": message,
                    "level": level,
                    "log_source": "session_replay",
                    "log_source_id": session_id,
                    # TRICKY: this is a hack to make sure the log entry is unique
                    # otherwise ClickHouse will assume that multiple entries
                    # with the same timestamp can be ignored
                    "instance_id": str(uuid4()),
                    "timestamp": timestamp,
                },
            )
