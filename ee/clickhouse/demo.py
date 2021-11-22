from typing import Dict, List
from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.session_recording_event import create_session_recording_event
from posthog.models.team import Team


def bulk_create_events(events: List[Dict], team: Team):
    from posthog.api.capture import capture_internal

    for event_data in events:
        capture_internal(
            event={"event": event_data["event"], "properties": event_data.get("properties", [])},
            distinct_id=event_data["distinct_id"],
            ip=None,
            site_url=None,
            now=event_data["timestamp"],
            sent_at=event_data["timestamp"],
            team_id=team.pk,
            event_uuid=uuid4(),
        )


def bulk_create_session_recording_events(events: List[Dict], **kw):
    for data in events:
        create_session_recording_event(**data, **kw, uuid=uuid4())  # type: ignore
