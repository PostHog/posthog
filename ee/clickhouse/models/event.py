import json
from datetime import datetime
from typing import Dict, Optional, Union

from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.events import INSERT_EVENT_SQL
from posthog.models.team import Team


def create_event(
    event: str,
    team: Team,
    distinct_id: str,
    properties: Optional[Dict] = {},
    timestamp: Optional[Union[datetime, str]] = datetime.now(),
    element_hash: Optional[str] = "",
) -> None:
    ch_client.execute(
        INSERT_EVENT_SQL,
        {
            "event": event,
            "properties": json.dumps(properties),
            "timestamp": timestamp,
            "team_id": team.pk,
            "distinct_id": distinct_id,
            "element_hash": element_hash,
        },
    )
