from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, cast

from dateutil.relativedelta import relativedelta
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.db.models import Q, QuerySet
from django.utils.timezone import now

from posthog.api.event import EventSerializer
from posthog.models import Event, Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.sessions_filter import SessionEventsFilter, SessionsFilter
from posthog.queries.base import BaseQuery, properties_to_Q
from posthog.queries.session_recording import filter_sessions_by_recordings

RunningSession = Dict
Session = Dict


class EventWithCurrentUrl:
    distinct_id: str
    timestamp: datetime
    current_url: Optional[str]


SESSIONS_LIST_DEFAULT_LIMIT = 1
SESSION_TIMEOUT = timedelta(minutes=30)
MAX_SESSION_DURATION = timedelta(hours=8)


class SessionsList:
    def run(self, filter: SessionsFilter, team: Team, *args, **kwargs) -> Tuple[List[Session], Optional[Dict]]:
        limit = int(kwargs.get("limit", SESSIONS_LIST_DEFAULT_LIMIT))
        offset = int(kwargs.get("offset", 0))

        sessions_builder = SessionListBuilder(
            self.events_query(filter, team, limit, offset).iterator(),
            offset=offset,
            limit=limit,
            last_page_last_seen=kwargs.get("last_seen", {}),
        )
        sessions_builder.build()

        return filter_sessions_by_recordings(team, sessions_builder.sessions, filter), sessions_builder.pagination

    def events_query(self, filter: SessionsFilter, team: Team, limit: int, offset: int) -> QuerySet:
        query = base_events_query(filter, team)
        return (
            query.filter(distinct_id__in=query.values("distinct_id").distinct()[: limit + offset + 1])
            .only("distinct_id", "timestamp")
            .annotate(current_url=KeyTextTransform("$current_url", "properties"))
        )


class SessionsListEvents(BaseQuery):
    def run(self, filter: SessionEventsFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        events = (
            Event.objects.filter(team=team)
            .filter(filter.date_filter_Q)
            .filter(distinct_id=filter.distinct_id)
            .order_by("timestamp")
        )
        return cast(List[Dict[str, Any]], EventSerializer(events, many=True, context={"people": None}).data)


class SessionListBuilder:
    def __init__(
        self,
        events_iterator,
        last_page_last_seen={},
        limit=50,
        offset=0,
        session_timeout=SESSION_TIMEOUT,
        max_session_duration=MAX_SESSION_DURATION,
    ):
        self.iterator = events_iterator
        self.last_page_last_seen: Dict[str, int] = last_page_last_seen
        self.limit: int = limit
        self.offset: int = offset
        self.session_timeout: timedelta = session_timeout
        self.max_session_duration: timedelta = max_session_duration

        self.running_sessions: Dict[str, RunningSession] = {}
        self._sessions: List[Session] = []

    @cached_property
    def sessions(self):
        return self._sessions[: self.limit]

    @cached_property
    def pagination(self):
        has_more = len(self._sessions) >= self.limit and (
            len(self._sessions) > self.limit or next(self.iterator, None) is not None
        )

        if has_more:
            return {"offset": self.offset + self.limit, "last_seen": self.next_page_last_seen()}
        else:
            return None

    @cached_property
    def next_page_start_timestamp(self):
        return min(session["end_time"].timestamp() for session in self._sessions)

    def next_page_last_seen(self):
        """
        Returns { distinct_id -> timestamp } mapping. All events >= timestamp should be ignored by that person

        This is needed to make pagination work.
        """
        result = {}
        for distinct_id, timestamp in self.last_page_last_seen.items():
            if timestamp <= self.next_page_start_timestamp:
                result[distinct_id] = timestamp

        for session in self.sessions:
            result[session["distinct_id"]] = int(session["start_time"].timestamp())
        return result

    def build(self):
        for index, event in enumerate(self.iterator):
            if (
                event.distinct_id not in self.last_page_last_seen
                or event.timestamp.timestamp() < self.last_page_last_seen[event.distinct_id]
            ):
                if event.distinct_id in self.running_sessions:
                    if self._has_session_timed_out(event.distinct_id, event.timestamp):
                        self._session_end(event.distinct_id)
                        self._session_start(event)
                    else:
                        self._session_update(event)
                elif len(self.running_sessions) + len(self._sessions) < self.limit:
                    self._session_start(event)

            if index % 300 == 0:
                self._sessions_check(event.timestamp)

            if len(self._sessions) >= self.limit:
                break

        self._sessions_check(None)

    def _session_start(self, event: EventWithCurrentUrl):
        self.running_sessions[event.distinct_id] = {
            "distinct_id": event.distinct_id,
            "end_time": event.timestamp,
            "event_count": 0,
            "start_url": event.current_url,
        }
        self._session_update(event)

    def _session_update(self, event: EventWithCurrentUrl):
        self.running_sessions[event.distinct_id]["start_time"] = event.timestamp
        self.running_sessions[event.distinct_id]["event_count"] += 1
        self.running_sessions[event.distinct_id]["end_url"] = event.current_url

    def _session_end(self, distinct_id: str):
        session = self.running_sessions[distinct_id]
        self._sessions.append(
            {
                **session,
                "global_session_id": f"{distinct_id}-{session['start_time']}",
                "length": (session["end_time"] - session["start_time"]).seconds,
            }
        )
        del self.running_sessions[distinct_id]

    def _has_session_timed_out(self, distinct_id: str, timestamp: datetime):
        session = self.running_sessions[distinct_id]
        return (
            session["start_time"] - timestamp > self.session_timeout
            or session["end_time"] - session["start_time"] > self.max_session_duration
        )

    def _sessions_check(self, timestamp: Optional[datetime]):
        for distinct_id in list(self.running_sessions.keys()):
            if timestamp is None or self._has_session_timed_out(distinct_id, timestamp):
                self._session_end(distinct_id)


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
        .filter(properties_to_Q(filter.properties, team_id=team.pk))
        .filter(date_filter)
        .order_by("-timestamp")
    )
