from typing import Any, Dict, List, cast

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import ClickhouseEventSerializer
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.sessions.list import SESSION_EVENTS
from posthog.models import Team
from posthog.models.filters.sessions_filter import SessionEventsFilter
from posthog.queries.base import BaseQuery


class SessionsListEvents(BaseQuery):
    def run(self, filter: SessionEventsFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        date_from, date_to, date_params = parse_timestamps(filter, team.pk)

        raw_events = sync_execute(
            SESSION_EVENTS.format(date_from=date_from, date_to=date_to),
            {"team_id": team.pk, "distinct_id": filter.distinct_id, **date_params},
        )

        return self._serialize(raw_events, cast(str, filter.distinct_id), team.pk)

    def _serialize(self, events: List[List[Any]], distinct_id: str, team_id: int) -> List[Dict]:
        data = []
        for uuid, event, properties, timestamp, elements_chain in events:
            data.append([uuid, event, properties, timestamp, team_id, None, distinct_id, elements_chain, None, None])
        return cast(List[Dict[str, Any]], ClickhouseEventSerializer(data, many=True, context={"people": None}).data)
