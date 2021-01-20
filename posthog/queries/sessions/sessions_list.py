from datetime import datetime
from typing import Dict, List, Optional, Tuple

from dateutil.relativedelta import relativedelta
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.db import connection
from django.db.models import Q, QuerySet
from django.db.models.expressions import ExpressionWrapper
from django.db.models.fields import BooleanField
from django.utils.timezone import now

from posthog.models import Event, Team
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.base import entity_to_Q, properties_to_Q
from posthog.queries.sessions.session_recording import filter_sessions_by_recordings
from posthog.queries.sessions.sessions_list_builder import SessionListBuilder

Session = Dict
SESSIONS_LIST_DEFAULT_LIMIT = 50


class SessionsList:
    def run(self, filter: SessionsFilter, team: Team, *args, **kwargs) -> Tuple[List[Session], Optional[Dict]]:
        limit = int(kwargs.get("limit", SESSIONS_LIST_DEFAULT_LIMIT))
        offset = int(filter.pagination.get("offset", 0))
        start_timestamp = filter.pagination.get("start_timestamp")
        date_filter = self.date_filter(filter)

        # :TRICKY: Query one extra person so we know when to stop pagination if all users on page are unique
        person_emails = self.query_people_in_range(team, filter, date_filter, limit=limit + offset + 1)

        sessions_builder = SessionListBuilder(
            self.events_query(team, filter, date_filter, list(person_emails.keys()), start_timestamp).iterator(),
            emails=person_emails,
            action_filter_count=len(filter.action_filters),
            offset=offset,
            limit=limit,
            last_page_last_seen=kwargs.get("last_seen", {}),
        )
        sessions_builder.build()

        return filter_sessions_by_recordings(team, sessions_builder.sessions, filter), sessions_builder.pagination

    def events_query(
        self,
        team: Team,
        filter: SessionsFilter,
        date_filter: Q,
        distinct_ids: List[str],
        start_timestamp: Optional[str],
    ) -> QuerySet:
        events = (
            Event.objects.filter(team=team)
            .filter(date_filter)
            .filter(distinct_id__in=distinct_ids)
            .order_by("-timestamp")
            .only("distinct_id", "timestamp")
            .annotate(current_url=KeyTextTransform("$current_url", "properties"))
        )
        if start_timestamp is not None:
            events = events.filter(timestamp__lt=datetime.fromtimestamp(float(start_timestamp)))

        keys = []
        for i, entity in enumerate(filter.action_filters):
            key = f"entity_{i}"
            events = events.annotate(
                **{key: ExpressionWrapper(entity_to_Q(entity, team.pk), output_field=BooleanField())}
            )
            keys.append(key)

        return events.values_list("distinct_id", "timestamp", "id", "current_url", *keys)

    def query_people_in_range(
        self, team: Team, filter: SessionsFilter, date_filter: Q, limit: int
    ) -> Dict[str, Optional[str]]:
        events_query = (
            Event.objects.filter(team=team)
            .add_person_id(team.pk)
            .filter(properties_to_Q(filter.person_filter_properties, team_id=team.pk))
            .filter(date_filter)
            .order_by("-timestamp")
            .only("distinct_id")
        )
        sql, params = events_query.query.sql_with_params()
        query = f"""
            SELECT DISTINCT ON(distinct_id) events.distinct_id, posthog_person.properties->>'email'
            FROM ({sql}) events
            LEFT OUTER JOIN
                posthog_persondistinctid ON posthog_persondistinctid.distinct_id = events.distinct_id AND posthog_persondistinctid.team_id = {team.pk}
            LEFT OUTER JOIN
                posthog_person ON posthog_person.id = posthog_persondistinctid.person_id
            LIMIT {limit}
        """
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            distinct_id_to_email = dict(cursor.fetchall())
            return distinct_id_to_email

    def date_filter(self, filter: SessionsFilter) -> Q:
        # if _date_from is not explicitely set we only want to get the last day worth of data
        # otherwise the query is very slow
        if filter._date_from and filter.date_to:
            return Q(timestamp__gte=filter.date_from, timestamp__lte=filter.date_to + relativedelta(days=1),)
        else:
            dt = now()
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            return Q(timestamp__gte=dt, timestamp__lte=dt + relativedelta(days=1))
