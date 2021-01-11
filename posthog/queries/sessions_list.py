from posthog.models.filters.mixins.utils import cached_property
from typing import Any, Dict, List

from dateutil.relativedelta import relativedelta
from django.db import connection
from django.db.models import Q, QuerySet
from django.db.models.query import Prefetch
from django.utils.timezone import now

from posthog.api.element import ElementSerializer
from posthog.models import Element, ElementGroup, Event, Team
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.base import BaseQuery, properties_to_Q
from posthog.queries.session_recording import filter_sessions_by_recordings
from posthog.queries.sessions import BaseSessions, Query, QueryParams
from posthog.utils import dict_from_cursor_fetchall

SESSIONS_LIST_DEFAULT_LIMIT = 50


class SessionsList(BaseQuery):
    def run(self, filter: SessionsFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        limit = int(kwargs.get("limit", SESSIONS_LIST_DEFAULT_LIMIT))
        offset = filter.offset

        sessions_builder = SessionListBuilder(
            self.build_events_query(filter, team, limit, offset).only('distinct_id', 'timestamp').iterator()
        )

        return sessions_builder.

    def build_events_query(self, filter: SessionsFilter, team: Team, limit: int, offset: int) -> QuerySet:
        query = self.base_events_query(filter, team)
        return query.filter(distinct_id__in=query.values('distinct_id').distinct()[:limit+offset])

    def base_events_query(self, filter: SessionsFilter, team: Team) -> QuerySet:
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

    # def _session_list(
    #     self, base_query: Query, params: QueryParams, team: Team, filter: SessionsFilter, limit: int, offset: int
    # ) -> List[Dict[str, Any]]:

    #     session_list = """
    #         SELECT
    #             *
    #         FROM (
    #             SELECT
    #                 global_session_id,
    #                 properties,
    #                 start_time,
    #                 end_time,
    #                 length,
    #                 sessions.distinct_id,
    #                 event_count,
    #                 events
    #             FROM (
    #                 SELECT
    #                     global_session_id,
    #                     count(1) as event_count,
    #                     MAX(distinct_id) as distinct_id,
    #                     EXTRACT('EPOCH' FROM (MAX(timestamp) - MIN(timestamp))) AS length,
    #                     MIN(timestamp) as start_time,
    #                     MAX(timestamp) as end_time,
    #                     array_agg(json_build_object( 'id', id, 'event', event, 'timestamp', timestamp, 'properties', properties, 'elements_hash', elements_hash) ORDER BY timestamp) as events
    #                 FROM
    #                     ({base_query}) as count
    #                 GROUP BY 1
    #             ) as sessions
    #             ORDER BY
    #                 start_time DESC
    #         ) as ordered_sessions
    #         OFFSET %s
    #         LIMIT %s
    #     """.format(
    #         base_query=base_query
    #     )

    #     with connection.cursor() as cursor:
    #         params = params + (team.pk, offset, limit,)
    #         cursor.execute(session_list, params)
    #         sessions = dict_from_cursor_fetchall(cursor)

    #         hash_ids = []
    #         for session in sessions:
    #             for event in session["events"]:
    #                 if event.get("elements_hash"):
    #                     hash_ids.append(event["elements_hash"])

    #         groups = self._prefetch_elements(hash_ids, team)

    #         for session in sessions:
    #             for event in session["events"]:
    #                 element_group = groups.get(event["elements_hash"])
    #                 if element_group:
    #                     event.update({"elements": ElementSerializer(element_group.element_set, many=True,).data})
    #                 else:
    #                     event.update({"elements": []})

    #     return filter_sessions_by_recordings(team, sessions, filter)

    # def _prefetch_elements(self, hash_ids: List[str], team: Team) -> Dict[str, ElementGroup]:
    #     if len(hash_ids) > 0:
    #         groups = ElementGroup.objects.filter(team=team, hash__in=hash_ids).prefetch_related(
    #             Prefetch("element_set", queryset=Element.objects.order_by("order"))
    #         )

    #         return {group.hash: group for group in groups}
    #     else:
    #         return {}

class SessionListBuilder:
    def __init__(self, events_iterator, last_page_last_seen = {}, limit = 50, session_timeout = 30 * 60, max_session_duration = 8 * 60 * 60):
        self.iterator = events_iterator
        self.last_page_last_seen = last_page_last_seen
        self.limit = limit
        self.session_timeout = session_timeout
        self.max_session_duration = max_session_duration

        self.running_sessions = {}
        self.sessions = []

        self._build()

    @cached_property
    def next_page_start_timestamp(self):
        return min(session["end_time"] for session in self.sessions)

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
            result[session["distinct_id"]] = session["start_time"]
        return result

    def _build(self):
        for index, event in enumerate(self.iterator):
            distinct_id = event.distinct_id
            timestamp = event.timestamp.timestamp()
            # print(distinct_id, timestamp, self.running_sessions.get(distinct_id), len(self.sessions), len(self.running_sessions))

            if timestamp < self.last_page_last_seen.get(distinct_id, float('inf')):
                if distinct_id in self.running_sessions:
                    if self._has_session_timed_out(distinct_id, timestamp):
                        self._session_end(distinct_id)
                        self._session_start(distinct_id, timestamp)
                    else:
                        self._session_update(distinct_id, timestamp)
                elif len(self.running_sessions) + len(self.sessions) < self.limit:
                    self._session_start(distinct_id, timestamp)

            if index % 300 == 0:
                self._sessions_check(timestamp)

            if len(self.sessions) >= self.limit:
                break

        self._sessions_check(None)

    def _session_start(self, distinct_id, timestamp):
        self.running_sessions[distinct_id] = { "distinct_id": distinct_id, "end_time": timestamp, "event_count": 0 }
        self._session_update(distinct_id, timestamp)

    def _session_update(self, distinct_id, timestamp):
        self.running_sessions[distinct_id]["start_time"] = timestamp
        self.running_sessions[distinct_id]["event_count"] += 1

    def _session_end(self, distinct_id):
        session = self.running_sessions[distinct_id]
        self.sessions.append({ **session, "duration": session["end_time"] - session["start_time"] })
        del self.running_sessions[distinct_id]

    def _has_session_timed_out(self, distinct_id, timestamp):
        session = self.running_sessions[distinct_id]
        return session["start_time"] - timestamp > self.session_timeout or session["end_time"] - session["start_time"] > self.max_session_duration

    def _sessions_check(self, timestamp):
        for distinct_id in list(self.running_sessions.keys()):
            if timestamp is None or self._has_session_timed_out(distinct_id, timestamp):
                self._session_end(distinct_id)


