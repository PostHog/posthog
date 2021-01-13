from datetime import datetime
from typing import Dict, List, Optional, Tuple

from dateutil.relativedelta import relativedelta
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.db.models import Q, QuerySet
from django.utils.timezone import now

from posthog.models import Event, Team
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.base import properties_to_Q
from posthog.queries.sessions.session_recording import filter_sessions_by_recordings
from posthog.queries.sessions.sessions_list_builder import SessionListBuilder

Session = Dict
SESSIONS_LIST_DEFAULT_LIMIT = 50


class SessionsList:
    def run(self, filter: SessionsFilter, team: Team, *args, **kwargs) -> Tuple[List[Session], Optional[Dict]]:
        limit = int(kwargs.get("limit", SESSIONS_LIST_DEFAULT_LIMIT))
        offset = int(kwargs.get("offset", 0))
        start_timestamp = kwargs.get("start_timestamp")

        sessions_builder = SessionListBuilder(
            self.events_query(filter, team, limit, offset, start_timestamp).iterator(),
            offset=offset,
            limit=limit,
            last_page_last_seen=kwargs.get("last_seen", {}),
        )
        sessions_builder.build()

        return filter_sessions_by_recordings(team, sessions_builder.sessions, filter), sessions_builder.pagination

    def events_query(
        self, filter: SessionsFilter, team: Team, limit: int, offset: int, start_timestamp: Optional[str]
    ) -> QuerySet:
        query = base_events_query(filter, team)
        events = (
            query.filter(distinct_id__in=query.values("distinct_id").distinct()[: limit + offset + 1])
            .only("distinct_id", "timestamp")
            .annotate(current_url=KeyTextTransform("$current_url", "properties"))
        )
        if start_timestamp is not None:
            events = events.filter(timestamp__lt=datetime.fromtimestamp(float(start_timestamp)))
        return events


def base_events_query(filter: SessionsFilter, team: Team) -> QuerySet:
    # if _date_from is not explicitely set we only want to get the last day worth of data
    # otherwise the query is very slow
    if filter._date_from and filter.date_to:
        date_filter = Q(timestamp__gte=filter.date_from, timestamp__lte=filter.date_to + relativedelta(days=1),)
    else:
        dt = now()
        dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        date_filter = Q(timestamp__gte=dt, timestamp__lte=dt + relativedelta(days=1))

    return (
        Event.objects.filter(team=team)
        .add_person_id(team.pk)
        .filter(properties_to_Q(filter.properties, team_id=team.pk))
        .filter(date_filter)
        .order_by("-timestamp")
    )
