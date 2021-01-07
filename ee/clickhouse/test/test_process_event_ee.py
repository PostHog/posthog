import json
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from dateutil import parser

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.element import chain_to_elements
from ee.clickhouse.process_event import process_event_ee
from ee.clickhouse.sql.session_recording_events import SESSION_RECORDING_EVENTS_TABLE
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.element import Element
from posthog.models.event import Event
from posthog.models.session_recording_event import SessionRecordingEvent
from posthog.models.utils import UUIDT
from posthog.tasks.test.test_process_event import test_process_event_factory


def get_session_recording_events():
    return [
        SessionRecordingEvent(
            id=event[0], session_id=event[1], distinct_id=event[2], snapshot_data=json.loads(event[3])
        )
        for event in sync_execute(
            "select uuid, session_id, distinct_id, snapshot_data from {}".format(SESSION_RECORDING_EVENTS_TABLE)
        )
    ]


def _get_events():
    return [
        Event(id=ev[0], properties=json.loads(ev[1]), distinct_id=ev[2], event=ev[3], timestamp=ev[4])
        for ev in sync_execute("select uuid, properties, distinct_id, event, timestamp from events")
    ]


def get_elements(event_id: Union[int, UUID]) -> List[Element]:
    return chain_to_elements(
        sync_execute("select elements_chain from events where uuid = %(id)s", {"id": event_id})[0][0]
    )


def _process_event_ee(
    distinct_id: str, ip: str, site_url: str, data: dict, team_id: int, now: str, sent_at: Optional[str],
) -> None:
    return process_event_ee(
        distinct_id=distinct_id,
        ip=ip,
        site_url=site_url,
        data=data,
        team_id=team_id,
        now=parser.isoparse(now),
        sent_at=parser.isoparse(sent_at) if sent_at else None,
        event_uuid=UUIDT(),
    )


class ClickhouseProcessEvent(
    ClickhouseTestMixin,
    test_process_event_factory(_process_event_ee, _get_events, get_session_recording_events, get_elements),  # type: ignore
):
    pass
