import json
from datetime import datetime
from typing import Dict, Optional, Union

from ee.clickhouse.client import ch_client
from posthog.models.team import Team

INSERT_EVENT_SQL = """
INSERT INTO events SELECT generateUUIDv4(), '{event}', '{properties}', parseDateTimeBestEffort('{timestamp}'), {team_id}, '{distinct_id}', '{element_hash}', now()
"""


def create_event(
    event: str,
    team: Team,
    distinct_id: str,
    properties: Optional[Dict] = {},
    timestamp: Optional[Union[datetime, str]] = datetime.now(),
    element_hash: Optional[str] = "",
) -> None:
    query = INSERT_EVENT_SQL.format(
        event=event,
        properties=json.dumps(properties),
        timestamp=timestamp,
        team_id=team.pk,
        distinct_id=distinct_id,
        element_hash=element_hash,
    )
    ch_client.execute(query)
