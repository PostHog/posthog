from typing import Dict, List
from uuid import uuid4

from ee.clickhouse.models.event import create_event


def bulk_create_events(events: List[Dict], **kw):
    for event_data in events:
        create_event(**event_data, **kw, event_uuid=uuid4())  # type: ignore
