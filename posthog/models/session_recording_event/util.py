import datetime
import json
import uuid
from typing import Any, Dict, List, Union

import structlog
from django.utils import timezone
from sentry_sdk import capture_exception

from posthog.client import sync_execute
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_SESSION_RECORDING_EVENTS
from posthog.models.session_recording_event.sql import (
    BULK_INSERT_SESSION_RECORDING_EVENT_SQL,
    INSERT_SESSION_RECORDING_EVENT_SQL,
)
from posthog.utils import cast_timestamp_or_now

logger = structlog.get_logger(__name__)

MAX_KAFKA_MESSAGE_LENGTH = 800_000
MAX_INSERT_LENGTH = 15_000_000


def create_session_recording_event(
    uuid: uuid.UUID,
    team_id: int,
    distinct_id: str,
    session_id: str,
    window_id: str,
    timestamp: Union[datetime.datetime, str],
    snapshot_data: dict,
) -> str:
    timestamp = cast_timestamp_or_now(timestamp)

    snapshot_data_json = json.dumps(snapshot_data)
    data = {
        "uuid": str(uuid),
        "team_id": team_id,
        "distinct_id": distinct_id,
        "session_id": session_id,
        "window_id": window_id,
        "snapshot_data": snapshot_data_json,
        "timestamp": timestamp,
        "created_at": timestamp,
    }
    if len(snapshot_data_json) <= MAX_KAFKA_MESSAGE_LENGTH:
        p = ClickhouseProducer()
        p.produce(sql=INSERT_SESSION_RECORDING_EVENT_SQL(), topic=KAFKA_SESSION_RECORDING_EVENTS, data=data)
    elif len(snapshot_data_json) <= MAX_INSERT_LENGTH:
        sync_execute(INSERT_SESSION_RECORDING_EVENT_SQL(), data, settings={"max_query_size": MAX_INSERT_LENGTH})
    else:
        capture_exception(Exception(f"Session recording event data too large - {len(snapshot_data_json)}"))

    return str(uuid)


def bulk_create_session_recording_event(events: List[Dict[str, Any]]) -> None:
    """
    Test only
    """
    # timestamp = cast_timestamp_or_now(timestamp)

    inserts = []
    params: Dict[str, Any] = {}
    for index, event in enumerate(events):

        timestamp = event["timestamp"].strftime("%Y-%m-%d %H:%M:%S.%f")
        data = {
            "uuid": str(event["uuid"]),
            "team_id": event["team_id"],
            "distinct_id": event["distinct_id"],
            "session_id": event["session_id"],
            "window_id": event.get("window_id"),
            "snapshot_data": json.dumps(event.get("snapshot_data", {})),
            "timestamp": timestamp,
            "created_at": timestamp,
        }
        inserts.append(
            """(

                %(uuid_{i})s,
                %(timestamp_{i})s,
                %(team_id_{i})s,
                %(distinct_id_{i})s,
                %(session_id_{i})s,
                %(window_id_{i})s,
                %(snapshot_data_{i})s,
                %(created_at_{i})s,
                now(),
                0
            )""".format(
                i=index
            )
        )

        params = {**params, **{"{}_{}".format(key, index): value for key, value in data.items()}}

    sync_execute(BULK_INSERT_SESSION_RECORDING_EVENT_SQL() + ", ".join(inserts), params, flush=False)


def get_recording_count_for_team_and_period(
    team_id: Union[str, int], begin: timezone.datetime, end: timezone.datetime
) -> int:
    result = sync_execute(
        """
        SELECT count(distinct session_id) as count
        FROM session_recording_events
        WHERE team_id = %(team_id)s
        AND timestamp between %(begin)s AND %(end)s
    """,
        {"team_id": str(team_id), "begin": begin, "end": end},
    )[0][0]
    return result
