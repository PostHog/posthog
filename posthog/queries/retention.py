import dataclasses
from typing import Any, Dict, List, Literal, Tuple, Union
from urllib.parse import urlencode

from django.db import connection
from django.db.models import Min
from django.db.models.expressions import Exists, F, OuterRef
from django.db.models.functions.datetime import TruncDay, TruncHour, TruncMonth, TruncWeek
from django.db.models.query import Prefetch, QuerySet
from django.db.models.query_utils import Q
from rest_framework.exceptions import ValidationError
from rest_framework.utils.serializer_helpers import ReturnDict
from sentry_sdk.api import capture_exception

from posthog.constants import RETENTION_FIRST_TIME, TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS, TRENDS_LINEAR
from posthog.models import Event, Filter, Team
from posthog.models.entity import Entity
from posthog.models.filters import RetentionFilter
from posthog.models.person import Person
from posthog.models.utils import namedtuplefetchall
from posthog.queries.base import BaseQuery, properties_to_Q


@dataclasses.dataclass
class AppearanceRow:
    """
    Container for the rows of the "Appearance count" query.
    """

    person_id: str
    appearance_count: int
    # This is actually the number of days from first event to the current event.
    appearances: List[float]


class Retention(BaseQuery):
    def __init__(self, base_uri: str = "/", **kwargs):
        self._base_uri = base_uri

    def process_table_result(
        self, resultset: Dict[Tuple[int, int], Dict[str, Any]], filter: RetentionFilter,
    ):

        result = [
            {
                "values": [
                    resultset.get((first_day, day), {"count": 0, "people": []})
                    for day in range(filter.total_intervals - first_day)
                ],
                "label": "{} {}".format(filter.period, first_day),
                "date": (filter.date_from + RetentionFilter.determine_time_delta(first_day, filter.period)[0]),
            }
            for first_day in range(filter.total_intervals)
        ]

        return result

    def process_graph_result(
        self, resultset: Dict[Tuple[int, int], Dict[str, Any]], filter: RetentionFilter,
    ):
        labels = []
        data = []
        days = []
        total_intervals = filter.total_intervals
        days_format = "%Y-%m-%d"

        if filter.period == "Hour":
            days_format += " %H:%M:%S"

        for interval_number in range(total_intervals):
            date = filter.date_from + interval_number * filter.period_increment
            days.append(date.strftime(days_format))
            label = "{} {}".format(filter.period, interval_number)
            labels.append(label)

            value_at_interval = resultset.get((0, interval_number), {"count": 0, "people": []}).get("count", 0)
            data.append(value_at_interval)

        normalized = [((float(val) / data[0]) if data[0] else 0) * 100 for val in data]

        result = {
            "data": normalized,
            "labels": labels,
            "count": data[0] if data else 0,
            "days": days,
            "people_urls": [
                self._construct_people_url_for_trend_interval(filter=filter, selected_interval=index)
                for index, _ in enumerate(data)
            ],
        }
        return [result]

    def _construct_people_url_for_trend_interval(self, filter: RetentionFilter, selected_interval: int):
        params = filter.with_data({"selected_interval": selected_interval}).to_params()
        return f"{self._base_uri}api/person/retention/?{urlencode(params)}"

    def _determine_query_params(self, filter: RetentionFilter, team: Team):

        period = filter.period
        is_first_time_retention = filter.retention_type == RETENTION_FIRST_TIME

        events: QuerySet = QuerySet()
        entity_condition, entity_condition_strigified = self.get_entity_condition(
            filter.target_entity, "first_event_date"
        )
        returning_condition, returning_condition_stringified = self.get_entity_condition(
            filter.returning_entity, "events"
        )
        events = Event.objects.filter(team_id=team.pk).add_person_id(team.pk).annotate(event_date=F("timestamp"))

        trunc, fields = self._get_trunc_func("timestamp", period)

        if is_first_time_retention:
            filtered_events = events.filter(properties_to_Q(filter.properties, team_id=team.pk))
            first_date = (
                filtered_events.filter(entity_condition)
                .values("person_id", "event", "action")
                .annotate(first_date=Min(trunc))
                .filter(filter.custom_date_filter_Q("first_date"))
                .distinct()
            )
            final_query = (
                filtered_events.filter(filter.date_filter_Q)
                .filter(returning_condition)
                .values_list("person_id", "event_date", "event", "action")
                .union(first_date.values_list("first_date", "person_id", "event", "action"))
            )
        else:
            filtered_events = events.filter(filter.date_filter_Q).filter(
                properties_to_Q(filter.properties, team_id=team.pk)
            )
            first_date = (
                filtered_events.filter(entity_condition)
                .annotate(first_date=trunc)
                .values("first_date", "person_id", "event", "action")
                .distinct()
            )

            final_query = (
                filtered_events.filter(returning_condition)
                .values_list("person_id", "event_date", "event", "action")
                .union(first_date.values_list("first_date", "person_id", "event", "action"))
            )

        start_params = (
            (filter.date_from, filter.date_from) if period == "Month" or period == "Hour" else (filter.date_from,)
        )

        event_query, events_query_params = final_query.query.sql_with_params()
        reference_event_query, first_date_params = first_date.query.sql_with_params()

        event_params = (filter.target_entity.id, filter.returning_entity.id, filter.target_entity.id)

        return (
            {
                "event_query": event_query,
                "reference_event_query": reference_event_query,
                "fields": fields,
                "return_condition": returning_condition_stringified,
                "target_condition": entity_condition_strigified,
            },
            start_params + events_query_params + first_date_params + event_params,
        )

    def _execute_sql(self, filter: RetentionFilter, team: Team,) -> Dict[Tuple[int, int], Dict[str, Any]]:
        format_fields, params = self._determine_query_params(filter, team)

        final_query = """
            SELECT
                {fields}
                COUNT(DISTINCT "events"."person_id"),
                array_agg(DISTINCT "events"."person_id") as people
            FROM ({event_query}) events
            LEFT JOIN ({reference_event_query}) first_event_date
              ON (events.person_id = first_event_date.person_id)
            WHERE event_date >= first_date
            AND {target_condition} AND {return_condition}
            OR ({target_condition} AND event_date = first_date)
            GROUP BY date, first_date
        """.format(
            **format_fields
        )

        with connection.cursor() as cursor:
            cursor.execute(final_query, params)
            data = namedtuplefetchall(cursor)

            by_dates = {}
            for row in data:
                by_dates.update({(int(row.first_date), int(row.date)): {"count": row.count}})

        return by_dates

    def run(self, filter: RetentionFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        resultset = self._execute_sql(filter, team)

        if filter.display == TRENDS_LINEAR:
            result = self.process_graph_result(resultset, filter)
        else:
            result = self.process_table_result(resultset, filter)
        return result

    def people(self, filter: RetentionFilter, team: Team, *args, **kwargs):
        results = self._retrieve_people(filter, team)
        return results

    def _retrieve_people(self, filter: RetentionFilter, team: Team):
        period = filter.period
        trunc, fields = self._get_trunc_func("timestamp", period)
        is_first_time_retention = filter.retention_type == RETENTION_FIRST_TIME
        entity_condition, _ = self.get_entity_condition(filter.target_entity, "events")
        returning_condition, _ = self.get_entity_condition(filter.returning_entity, "first_event_date")
        _entity_condition = returning_condition if filter.selected_interval > 0 else entity_condition

        events = Event.objects.filter(team_id=team.pk).add_person_id(team.pk)

        filtered_events = events.filter(filter.recurring_date_filter_Q()).filter(
            properties_to_Q(filter.properties, team_id=team.pk)
        )

        inner_events = (
            Event.objects.filter(team_id=team.pk)
            .filter(properties_to_Q(filter.properties, team_id=team.pk))
            .add_person_id(team.pk)
            .filter(**{"person_id": OuterRef("id")})
            .filter(entity_condition)
            .values("person_id")
            .annotate(first_date=Min(trunc))
            .filter(filter.reference_date_filter_Q("first_date"))
            .distinct()
            if is_first_time_retention
            else Event.objects.filter(team_id=team.pk)
            .filter(filter.reference_date_filter_Q())
            .filter(properties_to_Q(filter.properties, team_id=team.pk))
            .add_person_id(team.pk)
            .filter(**{"person_id": OuterRef("id")})
            .filter(entity_condition)
        )

        filtered_events = (
            filtered_events.filter(_entity_condition)
            .filter(
                Exists(Person.objects.filter(**{"id": OuterRef("person_id"),}).filter(Exists(inner_events)).only("id"))
            )
            .values("person_id")
            .distinct()
        ).all()

        people = Person.objects.filter(
            team=team, id__in=[p["person_id"] for p in filtered_events[filter.offset : filter.offset + 100]],
        )

        people = people.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))

        from posthog.api.person import PersonSerializer

        return PersonSerializer(people, many=True).data

    def people_in_period(self, filter: RetentionFilter, team: Team, *args, **kwargs):
        results = self._retrieve_people_in_period(filter, team)
        return results

    def _retrieve_people_in_period(self, filter: RetentionFilter, team: Team):
        filter = filter.with_data({"total_intervals": filter.total_intervals - filter.selected_interval})

        format_fields, params = self._determine_query_params(filter, team)

        final_query = """
            SELECT person_id, count(person_id) appearance_count, array_agg(date) appearances FROM (
                SELECT DISTINCT
                    {fields}
                    "events"."person_id"
                FROM ({event_query}) events
                LEFT JOIN ({reference_event_query}) first_event_date
                ON (events.person_id = first_event_date.person_id)
                WHERE event_date >= first_date
                AND {target_condition} AND {return_condition}
                OR ({target_condition} AND event_date = first_date)
            ) person_appearances
            WHERE first_date = 0
            GROUP BY person_id
            ORDER BY appearance_count DESC
            LIMIT %s OFFSET %s
        """.format(
            **format_fields
        )

        from posthog.api.person import PersonSerializer

        with connection.cursor() as cursor:
            cursor.execute(
                final_query, params + (100, filter.offset),
            )
            raw_results = cursor.fetchall()

            people_appearances = [
                AppearanceRow(person_id=result[0], appearance_count=result[1], appearances=result[2])
                for result in raw_results
            ]

            people_dict = {
                person.pk: PersonSerializer(person).data
                for person in Person.objects.filter(
                    team_id=team.pk, id__in=[person.person_id for person in people_appearances]
                )
            }

            return self.process_people_in_period(filter, people_appearances, people_dict)

    def process_people_in_period(
        self, filter: RetentionFilter, people_appearances: List[AppearanceRow], people_dict: Dict[str, ReturnDict]
    ) -> List[Dict[Literal["person", "appearances"], Any]]:
        marker_length = filter.total_intervals
        result: List[Dict[Literal["person", "appearances"], Any]] = []
        for person in people_appearances:
            # NOTE: This try/except shouldn't be necessary but there do seem to be a handful of missing persons that can't be looked up
            try:
                result.append(
                    {
                        "person": people_dict[person.person_id],
                        "appearances": appearance_to_markers(sorted(person.appearances), marker_length),
                    }
                )
            except Exception as e:
                capture_exception(e)
                continue

        return result

    def get_entity_condition(self, entity: Entity, table: str) -> Tuple[Q, str]:
        if entity.type == TREND_FILTER_TYPE_EVENTS:
            return Q(event=entity.id), "{}.event = %s".format(table)
        elif entity.type == TREND_FILTER_TYPE_ACTIONS:
            return Q(action__pk=entity.id), "{}.action_id = %s".format(table)
        else:
            raise ValidationError(f"Entity type not supported")

    def _get_trunc_func(
        self, subject: str, period: str
    ) -> Tuple[Union[TruncHour, TruncDay, TruncWeek, TruncMonth], str]:
        if period == "Hour":
            fields = """
            FLOOR(DATE_PART('day', first_date - %s) * 24 + DATE_PART('hour', first_date - %s)) AS first_date,
            FLOOR(DATE_PART('day', event_date - first_date) * 24 + DATE_PART('hour', event_date - first_date)) AS date,
            """
            return TruncHour(subject), fields
        elif period == "Day":
            fields = """
            FLOOR(DATE_PART('day', first_date - %s)) AS first_date,
            FLOOR(DATE_PART('day', event_date - first_date)) AS date,
            """
            return TruncDay(subject), fields
        elif period == "Week":
            fields = """
            FLOOR(DATE_PART('day', first_date - %s) / 7) AS first_date,
            FLOOR(DATE_PART('day', event_date - first_date) / 7) AS date,
            """
            return TruncWeek(subject), fields
        elif period == "Month":
            fields = """
            FLOOR((DATE_PART('year', first_date) - DATE_PART('year', %s)) * 12 + DATE_PART('month', first_date) - DATE_PART('month', %s)) AS first_date,
            FLOOR((DATE_PART('year', event_date) - DATE_PART('year', first_date)) * 12 + DATE_PART('month', event_date) - DATE_PART('month', first_date)) AS date,
            """
            return TruncMonth(subject), fields
        else:
            raise ValidationError(f"Period {period} is unsupported.")


def appearance_to_markers(appearance_dates: List[float], num_intervals: int) -> List[int]:
    return [interval_number in appearance_dates for interval_number in range(num_intervals)]
