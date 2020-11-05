import random
import string
from datetime import timedelta
from typing import Any, Dict, List, Tuple, Union

from dateutil.relativedelta import relativedelta
from django.core.cache import cache
from django.db import connection
from django.db.models.functions.datetime import TruncDay, TruncHour, TruncMonth, TruncWeek
from django.db.models.query import QuerySet
from django.utils.timezone import now

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.models import Event, Filter, Team
from posthog.models.entity import Entity
from posthog.models.utils import namedtuplefetchall
from posthog.queries.base import BaseQuery
from posthog.utils import generate_cache_key


class Retention(BaseQuery):
    def calculate_retention(self, filter: Filter, team: Team, total_intervals=11):
        period = filter.period or "Day"
        tdelta, t1 = self.determineTimedelta(total_intervals, period)
        filter._date_to = ((filter.date_to if filter.date_to else now()) + t1).isoformat()

        if period == "Hour":
            date_to = filter.date_to if filter.date_to else now()
            date_from = date_to - tdelta
        else:

            date_to = (filter.date_to if filter.date_to else now()).replace(hour=0, minute=0, second=0, microsecond=0)
            date_from = date_to - tdelta

        filter._date_from = date_from.isoformat()
        filter._date_to = date_to.isoformat()

        resultset = self._execute_sql(filter, team)

        result = [
            {
                "values": [
                    resultset.get((first_day, day), {"count": 0, "people": []})
                    for day in range(total_intervals - first_day)
                ],
                "label": "{} {}".format(period, first_day),
                "date": (date_from + self.determineTimedelta(first_day, period)[0]),
            }
            for first_day in range(total_intervals)
        ]

        return result

    def _execute_sql(self, filter, team):

        period = filter.period
        events: QuerySet = QuerySet()
        entity = (
            Entity({"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS})
            if not filter.target_entity
            else filter.target_entity
        )
        if entity.type == TREND_FILTER_TYPE_EVENTS:
            events = Event.objects.filter_by_event_with_people(event=entity.id, team_id=team.id)
        elif entity.type == TREND_FILTER_TYPE_ACTIONS:
            events = Event.objects.filter(action__pk=entity.id).add_person_id(team.id)

        filtered_events = events.filter(filter.date_filter_Q).filter(filter.properties_to_Q(team_id=team.pk))
        trunc, fields = self._get_trunc_func("timestamp", period)
        first_date = filtered_events.annotate(first_date=trunc).values("first_date", "person_id").distinct()

        events_query, events_query_params = filtered_events.query.sql_with_params()
        first_date_query, first_date_params = first_date.query.sql_with_params()

        full_query = """
            SELECT
                {fields}
                COUNT(DISTINCT "events"."person_id"),
                array_agg(DISTINCT "events"."person_id") as people
            FROM ({events_query}) events
            LEFT JOIN ({first_date_query}) first_event_date
              ON (events.person_id = first_event_date.person_id)
            WHERE timestamp >= first_date
            GROUP BY date, first_date
        """

        full_query = full_query.format(events_query=events_query, first_date_query=first_date_query, fields=fields)

        start_params = (
            (filter.date_from, filter.date_from) if period == "Month" or period == "Hour" else (filter.date_from,)
        )

        with connection.cursor() as cursor:
            cursor.execute(
                full_query, start_params + events_query_params + first_date_params,
            )
            data = namedtuplefetchall(cursor)

            scores: dict = {}
            for datum in data:
                key = round(datum.first_date, 1)
                if not scores.get(key, None):
                    scores.update({key: {}})
                for person in datum.people:
                    if not scores[key].get(person, None):
                        scores[key].update({person: 1})
                    else:
                        scores[key][person] += 1

        by_dates = {}
        for row in data:
            people = sorted(row.people, key=lambda p: scores[round(row.first_date, 1)][int(p)], reverse=True,)

            random_key = "".join(
                random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(10)
            )
            cache_key = generate_cache_key("{}{}{}".format(random_key, str(round(row.first_date, 0)), str(team.pk)))
            cache.set(
                cache_key, people, 600,
            )
            by_dates.update(
                {
                    (int(row.first_date), int(row.date)): {
                        "count": row.count,
                        "people": people[0:100],
                        "offset": 100,
                        "next": cache_key if len(people) > 100 else None,
                    }
                }
            )

        return by_dates

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return self.calculate_retention(filter=filter, team=team, total_intervals=kwargs.get("total_intervals", 11),)

    def determineTimedelta(
        self, total_intervals: int, period: str
    ) -> Tuple[Union[timedelta, relativedelta], Union[timedelta, relativedelta]]:
        if period == "Hour":
            return timedelta(hours=total_intervals), timedelta(hours=1)
        elif period == "Week":
            return timedelta(weeks=total_intervals), timedelta(weeks=1)
        elif period == "Month":
            return relativedelta(months=total_intervals), relativedelta(months=1)
        elif period == "Day":
            return timedelta(days=total_intervals), timedelta(days=1)
        else:
            raise ValueError(f"Period {period} is unsupported.")

    def _get_trunc_func(
        self, subject: str, period: str
    ) -> Tuple[Union[TruncHour, TruncDay, TruncWeek, TruncMonth], str]:
        if period == "Hour":
            fields = """
            FLOOR(DATE_PART('day', first_date - %s) * 24 + DATE_PART('hour', first_date - %s)) AS first_date,
            FLOOR(DATE_PART('day', timestamp - first_date) * 24 + DATE_PART('hour', timestamp - first_date)) AS date,
            """
            return TruncHour(subject), fields
        elif period == "Day":
            fields = """
            FLOOR(DATE_PART('day', first_date - %s)) AS first_date,
            FLOOR(DATE_PART('day', timestamp - first_date)) AS date,
            """
            return TruncDay(subject), fields
        elif period == "Week":
            fields = """
            FLOOR(DATE_PART('day', first_date - %s) / 7) AS first_date,
            FLOOR(DATE_PART('day', timestamp - first_date) / 7) AS date,
            """
            return TruncWeek(subject), fields
        elif period == "Month":
            fields = """
            FLOOR((DATE_PART('year', first_date) - DATE_PART('year', %s)) * 12 + DATE_PART('month', first_date) - DATE_PART('month', %s)) AS first_date,
            FLOOR((DATE_PART('year', timestamp) - DATE_PART('year', first_date)) * 12 + DATE_PART('month', timestamp) - DATE_PART('month', first_date)) AS date,
            """
            return TruncMonth(subject), fields
        else:
            raise ValueError(f"Period {period} is unsupported.")
