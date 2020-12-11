from typing import Any, Dict, List

from dateutil.relativedelta import relativedelta
from django.db import connection
from django.db.models import Q, QuerySet
from django.utils.timezone import now

from posthog.api.element import ElementSerializer
from posthog.models import ElementGroup, Event, Team
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.session_recording import filter_sessions_by_recordings
from posthog.queries.sessions import BaseSessions, Query, QueryParams
from posthog.utils import dict_from_cursor_fetchall

SESSIONS_LIST_DEFAULT_LIMIT = 50


class SessionsList(BaseSessions):
    def run(self, filter: SessionsFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        events = self.events_query(filter, team)

        limit = int(kwargs.get("limit", SESSIONS_LIST_DEFAULT_LIMIT))
        offset = filter.offset

        return self.calculate_sessions(events, filter, team, limit, offset)

    def calculate_sessions(
        self, events: QuerySet, filter: SessionsFilter, team: Team, limit: int, offset: int
    ) -> List[Dict[str, Any]]:

        # if _date_from is not explicitely set we only want to get the last day worth of data
        # otherwise the query is very slow
        if filter._date_from and filter.date_to:
            _date_gte = Q(timestamp__gte=filter.date_from, timestamp__lte=filter.date_to + relativedelta(days=1),)
        else:
            dt = now()
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            _date_gte = Q(timestamp__gte=dt, timestamp__lte=dt + relativedelta(days=1))

        all_sessions, sessions_sql_params = self.build_all_sessions_query(events, _date_gte)
        return self._session_list(all_sessions, sessions_sql_params, team, filter, limit, offset)

    def _session_list(
        self, base_query: Query, params: QueryParams, team: Team, filter: SessionsFilter, limit: int, offset: int
    ) -> List[Dict[str, Any]]:

        session_list = """
            SELECT
                *
            FROM (
                SELECT
                    global_session_id,
                    properties,
                    start_time,
                    end_time,
                    length,
                    sessions.distinct_id,
                    event_count,
                    events
                FROM (
                    SELECT
                        global_session_id,
                        count(1) as event_count,
                        MAX(distinct_id) as distinct_id,
                        EXTRACT('EPOCH' FROM (MAX(timestamp) - MIN(timestamp))) AS length,
                        MIN(timestamp) as start_time,
                        MAX(timestamp) as end_time,
                        array_agg(json_build_object( 'id', id, 'event', event, 'timestamp', timestamp, 'properties', properties, 'elements_hash', elements_hash) ORDER BY timestamp) as events
                    FROM
                        ({base_query}) as count
                    GROUP BY 1
                ) as sessions
                LEFT OUTER JOIN
                    posthog_persondistinctid ON posthog_persondistinctid.distinct_id = sessions.distinct_id AND posthog_persondistinctid.team_id = %s
                LEFT OUTER JOIN
                    posthog_person ON posthog_person.id = posthog_persondistinctid.person_id
                ORDER BY
                    start_time DESC
            ) as ordered_sessions
            OFFSET %s
            LIMIT %s
        """.format(
            base_query=base_query
        )

        with connection.cursor() as cursor:
            params = params + (team.pk, offset, limit,)
            cursor.execute(session_list, params)
            sessions = dict_from_cursor_fetchall(cursor)

            hash_ids = []
            for session in sessions:
                for event in session["events"]:
                    if event.get("elements_hash"):
                        hash_ids.append(event["elements_hash"])

            groups = self._prefetch_elements(hash_ids, team)

            for session in sessions:
                for event in session["events"]:
                    try:
                        event.update(
                            {
                                "elements": ElementSerializer(
                                    [group for group in groups if group.hash == event["elements_hash"]][0]
                                    .element_set.all()
                                    .order_by("order"),
                                    many=True,
                                ).data
                            }
                        )
                    except IndexError:
                        event.update({"elements": []})
        return filter_sessions_by_recordings(team, sessions, filter)

    def _prefetch_elements(self, hash_ids: List[str], team: Team) -> QuerySet:
        groups = ElementGroup.objects.none()
        if len(hash_ids) > 0:
            groups = ElementGroup.objects.filter(team=team, hash__in=hash_ids).prefetch_related("element_set")
        return groups
