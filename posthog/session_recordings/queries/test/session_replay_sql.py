from datetime import datetime
from typing import Optional, List, Dict
from uuid import uuid4

from posthog.clickhouse.log_entries import INSERT_LOG_ENTRY_SQL
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import (
    KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
    KAFKA_LOG_ENTRIES,
)
from posthog.session_recordings.management.data_utils import (
    INSERT_SINGLE_SESSION_REPLAY,
    for_direct_session_replay_insertion,
)


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

    data, timestamp, _ = for_direct_session_replay_insertion(
        team_id,
        session_id,
        distinct_id,
        first_timestamp,
        last_timestamp,
        first_url,
        click_count,
        keypress_count,
        mouse_activity_count,
        active_milliseconds,
        console_log_count,
        console_warn_count,
        console_error_count,
    )
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
