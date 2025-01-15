import datetime

from posthog.models import Team
from posthog.test.base import _create_event


def create_event(
    distinct_id: str,
    timestamp: datetime.datetime,
    team: Team,
    event_name: str = "$pageview",
    properties: dict | None = None,
) -> str:
    if properties is None:
        properties = {"$os": "Windows 95", "$current_url": "aloha.com/2"}
    return _create_event(
        team=team,
        event=event_name,
        timestamp=timestamp,
        distinct_id=distinct_id,
        properties=properties,
    )
