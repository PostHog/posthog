from typing import Any, Dict, List, cast

from posthog.api.event import EventSerializer
from posthog.models import Event, Team
from posthog.models.filters.sessions_filter import SessionEventsFilter
from posthog.queries.base import BaseQuery


class SessionsListEvents(BaseQuery):
    def run(self, filter: SessionEventsFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        events = (
            Event.objects.filter(team=team)
            .filter(filter.date_filter_Q)
            .filter(distinct_id=filter.distinct_id)
            .order_by("timestamp")
        )
        return cast(List[Dict[str, Any]], EventSerializer(events, many=True, context={"people": None}).data)
