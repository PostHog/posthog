from datetime import datetime
from typing import Dict, List, Optional, Tuple

from dateutil.relativedelta import relativedelta
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.db import connection
from django.db.models import Q, QuerySet
from django.db.models.expressions import ExpressionWrapper
from django.db.models.fields import BooleanField
from django.utils.timezone import now

from posthog.models import Event, Person, Team
from posthog.models.filters.filter import Filter
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.base import entity_to_Q, properties_to_Q
from posthog.queries.sessions.session_recording import filter_sessions_by_recordings
from posthog.queries.sessions.sessions_list_builder import SessionListBuilder

Session = Dict
SESSIONS_LIST_DEFAULT_LIMIT = 50


class SessionsList:
    filter: Filter
    team: Team
    limit: int

    def __init__(self, filter: SessionsFilter, team: Team, limit=SESSIONS_LIST_DEFAULT_LIMIT):
        self.filter = filter
        self.team = team
        self.limit = limit

    @classmethod
    def run(cls, filter: SessionsFilter, team: Team, *args, **kwargs) -> Tuple[List[Dict], Optional[Dict]]:
        "Sessions queries do post-filtering based on session recordings. This makes sure we return some data every page"
        limit = kwargs.get("limit", SESSIONS_LIST_DEFAULT_LIMIT)

        results = []

        while True:
            page, pagination = cls(filter, team, limit=limit).fetch_page()
            results.extend(page)

            if len(results) >= limit or pagination is None:
                return results, pagination
            filter = filter.with_data({"pagination": pagination})

    def fetch_page(self) -> Tuple[List[Session], Optional[Dict]]:
        distinct_id_offset = self.filter.pagination.get("distinct_id_offset", 0)
        start_timestamp = self.filter.pagination.get("start_timestamp")

        person_emails = self.query_people_in_range(limit=self.limit + distinct_id_offset)

        sessions_builder = SessionListBuilder(
            self.events_query(list(person_emails.keys()), start_timestamp).iterator(),
            emails=person_emails,
            action_filter_count=len(self.filter.action_filters),
            distinct_id_offset=distinct_id_offset,
            start_timestamp=start_timestamp,
            limit=self.limit,
            last_page_last_seen=self.filter.pagination.get("last_seen", {}),
        )
        sessions_builder.build()

        return (
            filter_sessions_by_recordings(self.team, sessions_builder.sessions, self.filter),
            sessions_builder.pagination,
        )

    def events_query(self, distinct_ids: List[str], start_timestamp: Optional[str],) -> QuerySet:
        events = (
            Event.objects.filter(team=self.team)
            .filter(self.date_filter())
            .filter(distinct_id__in=distinct_ids)
            .order_by("-timestamp")
            .only("distinct_id", "timestamp")
            .annotate(current_url=KeyTextTransform("$current_url", "properties"))
        )
        if start_timestamp is not None:
            events = events.filter(timestamp__lt=datetime.fromtimestamp(float(start_timestamp)))

        keys = []
        for i, entity in enumerate(self.filter.action_filters):
            key = f"entity_{i}"
            events = events.annotate(
                **{key: ExpressionWrapper(entity_to_Q(entity, self.team.pk), output_field=BooleanField())}
            )
            keys.append(key)

        return events.values_list("distinct_id", "timestamp", "id", "current_url", *keys)

    def query_people_in_range(self, limit: int) -> Dict[str, Optional[str]]:
        if self.filter.distinct_id:
            person = Person.objects.filter(
                team=self.team, persondistinctid__distinct_id=self.filter.distinct_id
            ).first()
            return (
                {distinct_id: person.properties.get("email") for distinct_id in person.distinct_ids} if person else {}
            )

        events_query = (
            Event.objects.filter(team=self.team)
            .add_person_id(self.team.pk)
            .filter(properties_to_Q(self.filter.person_filter_properties, team_id=self.team.pk))
            .filter(self.date_filter())
            .order_by("-timestamp")
        )
        sql, params = events_query.query.sql_with_params()
        query = f"""
            SELECT events.distinct_id, MIN(posthog_person.properties->>'email')
            FROM ({sql}) events
            LEFT OUTER JOIN
                posthog_persondistinctid ON posthog_persondistinctid.distinct_id = events.distinct_id AND posthog_persondistinctid.team_id = {self.team.pk}
            LEFT OUTER JOIN
                posthog_person ON posthog_person.id = posthog_persondistinctid.person_id
            GROUP BY events.distinct_id
            ORDER BY MAX(events.timestamp) DESC
            LIMIT {limit}
        """
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            distinct_id_to_email = dict(cursor.fetchall())
            return distinct_id_to_email

    def date_filter(self) -> Q:
        # if _date_from is not explicitely set we only want to get the last day worth of data
        # otherwise the query is very slow
        if self.filter._date_from and self.filter.date_to:
            return Q(timestamp__gte=self.filter.date_from, timestamp__lte=self.filter.date_to + relativedelta(days=1),)
        else:
            dt = now()
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            return Q(timestamp__gte=dt, timestamp__lte=dt + relativedelta(days=1))
