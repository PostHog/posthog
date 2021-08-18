from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from dateutil.relativedelta import relativedelta
from django.db import connection
from django.db.models.query import Prefetch
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.entity import Entity
from posthog.models.event import Event
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.queries.base import TIME_IN_SECONDS, filter_events, filter_persons
from posthog.utils import queryset_to_named_query

LIFECYCLE_SQL = """
SELECT array_agg(day_start ORDER BY day_start ASC), array_agg(counts ORDER BY day_start ASC), status FROM  (
    SELECT (SUM(counts) :: int) as counts, day_start, status
    FROM (
             SELECT date_trunc(%(interval)s, %(after_date_to)s -
                                      n * INTERVAL %(one_interval)s) as day_start,
                    0                                               AS counts,
                    status
             from generate_series(1, %(num_intervals)s) as n
                      CROSS JOIN
                  (
                      SELECT status
                      FROM unnest(ARRAY ['new', 'returning', 'resurrecting', 'dormant']) status
                  ) as sec
             UNION ALL
             SELECT subsequent_day,
                        CASE WHEN status = 'dormant' THEN count(DISTINCT person_id) * -1
                        ELSE count(DISTINCT person_id)
                        END as counts,
                        status
             FROM (
                               SELECT e.person_id,
                                      subsequent_day,
                                      CASE
                                          WHEN base_day = to_timestamp('0000-00-00 00:00:00', 'YYYY-MM-DD HH24:MI:SS')
                                              THEN 'dormant'
                                          WHEN subsequent_day = base_day + INTERVAL %(one_interval)s THEN 'returning'
                                          WHEN subsequent_day > earliest + INTERVAL %(one_interval)s THEN 'resurrecting'
                                          ELSE 'new'
                                          END as status
                               FROM (
                                        SELECT test.person_id, base_day, min(subsequent_day) as subsequent_day
                                        FROM (
                                                 SELECT events.person_id, day as base_day, sub_day as subsequent_day
                                                 FROM (
                                                          SELECT DISTINCT _person_id as person_id,
                                                                          DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') AS "day"
                                                          FROM ({events}) posthog_event
                                                          {action_join}
                                                            JOIN
                                                            (SELECT person_id as _person_id,
                                                                    distinct_id
                                                                FROM posthog_persondistinctid
                                                                WHERE team_id = %(team_id)s) pdi on posthog_event.distinct_id = pdi.distinct_id
                                                          WHERE team_id = %(team_id)s
                                                            AND {event_condition}
                                                          GROUP BY _person_id, day
                                                          HAVING DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') >=
                                                                 %(prev_date_from)s
                                                             AND DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') <=
                                                                 %(date_to)s
                                                      ) base
                                                          JOIN (
                                                     SELECT DISTINCT _person_id as person_id,
                                                                     DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') AS "sub_day"
                                                     FROM ({events}) posthog_event
                                                     {action_join}
                                                        JOIN
                                                        (SELECT person_id as _person_id,
                                                                distinct_id
                                                            FROM posthog_persondistinctid
                                                            WHERE team_id = %(team_id)s) pdi on posthog_event.distinct_id = pdi.distinct_id
                                                     WHERE team_id = %(team_id)s
                                                       AND {event_condition}
                                                     GROUP BY _person_id, sub_day
                                                     HAVING DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') >=
                                                            %(prev_date_from)s
                                                        AND DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') <=
                                                            %(date_to)s
                                                 ) events ON base.person_id = events.person_id
                                                 WHERE sub_day > day
                                             ) test
                                        GROUP BY person_id, base_day
                                        UNION ALL
                                        SELECT person_id, min(day) as base_day, min(day) as subsequent_day
                                        FROM (
                                                 SELECT DISTINCT _person_id as person_id,
                                                                 DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') AS "day"
                                                 FROM ({events}) posthog_event
                                                 {action_join}
                                                    JOIN
                                                    (SELECT person_id as _person_id,
                                                            distinct_id
                                                        FROM posthog_persondistinctid
                                                        WHERE team_id = %(team_id)s) pdi on posthog_event.distinct_id = pdi.distinct_id
                                                 WHERE team_id = %(team_id)s
                                                   AND {event_condition}
                                                 GROUP BY _person_id, day
                                                 HAVING DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') >=
                                                        %(prev_date_from)s
                                                    AND DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') <=
                                                        %(date_to)s
                                             ) base
                                        GROUP BY person_id
                                        UNION ALL
                                        SELECT person_id, base_day, subsequent_day
                                        FROM (
                                                 SELECT *
                                                 FROM (
                                                          SELECT *,
                                                                 LAG(person_id, 1) OVER ( ORDER BY person_id)    lag_id,
                                                                 LAG(subsequent_day, 1) OVER ( ORDER BY person_id) lag_day
                                                          FROM (
                                                                   SELECT person_id, total as base_day, day_start as subsequent_day
                                                                   FROM (
                                                                            SELECT DISTINCT _person_id as person_id,
                                                                                            array_agg(date_trunc(%(interval)s, posthog_event.timestamp)) as day
                                                                            FROM ({events}) posthog_event
                                                                            {action_join}
                                                                            JOIN
                                                                            (SELECT person_id as _person_id,
                                                                                    distinct_id
                                                                                FROM posthog_persondistinctid
                                                                                WHERE team_id = %(team_id)s) pdi on posthog_event.distinct_id = pdi.distinct_id
                                                                            WHERE team_id = %(team_id)s
                                                                              AND {event_condition}
                                                                              AND posthog_event.timestamp <= %(after_date_to)s
                                                                              AND DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') >=
                                                                                  %(date_from)s
                                                                            GROUP BY _person_id
                                                                        ) as e
                                                                            CROSS JOIN (
                                                                       SELECT to_timestamp('0000-00-00 00:00:00', 'YYYY-MM-DD HH24:MI:SS') AS total,
                                                                              DATE_TRUNC(%(interval)s,
                                                                                         %(after_date_to)s -
                                                                                         n * INTERVAL %(one_interval)s) as day_start
                                                                       FROM generate_series(1, %(num_intervals)s) as n
                                                                   ) as b
                                                                   WHERE day_start != ALL (day)
                                                                   ORDER BY person_id, subsequent_day ASC
                                                               ) dormant_days
                                                               ORDER BY person_id, subsequent_day ASC
                                                      ) lagged
                                                 WHERE ((lag_id IS NULL OR lag_id != lagged.person_id) AND subsequent_day != DATE_TRUNC(%(interval)s, %(date_from)s + INTERVAL %(one_interval)s -  INTERVAL %(sub_interval)s))
                                                    OR (lag_id = lagged.person_id AND lag_day < subsequent_day - INTERVAL %(one_interval)s)
                                             ) dormant_days
                                    ) e
                                        JOIN (
                                   SELECT DISTINCT _person_id as person_id,
                                                   DATE_TRUNC(%(interval)s,
                                                              min("posthog_event"."timestamp") AT TIME ZONE 'UTC') earliest
                                   FROM ({earliest_events}) posthog_event
                                    JOIN
                                    (SELECT person_id as _person_id,
                                            distinct_id
                                        FROM posthog_persondistinctid
                                        WHERE team_id = %(team_id)s) pdi on posthog_event.distinct_id = pdi.distinct_id
                                   {action_join}
                                   WHERE team_id = %(team_id)s
                                     AND {event_condition}
                                   GROUP BY _person_id
                               ) earliest ON e.person_id = earliest.person_id
                  ) grouped_counts
             WHERE subsequent_day <= %(date_to)s
               AND subsequent_day >= %(date_from)s
             GROUP BY subsequent_day, status
         ) counts
    GROUP BY day_start, status
    ) arrayified
GROUP BY status
"""

ACTION_JOIN = """
INNER JOIN posthog_action_events
ON posthog_event.id = posthog_action_events.event_id
"""

LIFECYCLE_PEOPLE_SQL = """
SELECT person_id, subsequent_day, status
FROM (
        SELECT e.person_id,
                subsequent_day,
                CASE
                    WHEN base_day = to_timestamp('0000-00-00 00:00:00', 'YYYY-MM-DD HH24:MI:SS')
                        THEN 'dormant'
                    WHEN subsequent_day = base_day + INTERVAL %(one_interval)s THEN 'returning'
                    WHEN subsequent_day > earliest + INTERVAL %(one_interval)s THEN 'resurrecting'
                    ELSE 'new'
                    END as status
        FROM (
                SELECT test.person_id, base_day, min(subsequent_day) as subsequent_day
                FROM (
                            SELECT events.person_id, day as base_day, sub_day as subsequent_day
                            FROM (
                                    SELECT DISTINCT _person_id as person_id,
                                                    DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') AS "day"
                                    FROM ({events}) posthog_event
                                    {action_join}
                                    JOIN
                                    (SELECT person_id as _person_id,
                                            distinct_id
                                        FROM posthog_persondistinctid
                                        WHERE team_id = %(team_id)s) pdi on posthog_event.distinct_id = pdi.distinct_id
                                    WHERE team_id = %(team_id)s
                                    AND {event_condition}
                                    GROUP BY _person_id, day
                                    HAVING DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') >=
                                            %(prev_date_from)s
                                        AND DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') <=
                                            %(date_to)s
                                ) base
                                    JOIN (
                                SELECT DISTINCT _person_id as person_id,
                                                DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') AS "sub_day"
                                FROM ({events}) posthog_event
                                {action_join}
                                JOIN
                                (SELECT person_id as _person_id,
                                        distinct_id
                                    FROM posthog_persondistinctid
                                    WHERE team_id = %(team_id)s) pdi on posthog_event.distinct_id = pdi.distinct_id
                                WHERE team_id = %(team_id)s
                                AND {event_condition}
                                GROUP BY _person_id, sub_day
                                HAVING DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') >=
                                    %(prev_date_from)s
                                AND DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') <=
                                    %(date_to)s
                            ) events ON base.person_id = events.person_id
                            WHERE sub_day > day
                        ) test
                GROUP BY person_id, base_day
                UNION ALL
                SELECT person_id, min(day) as base_day, min(day) as subsequent_day
                FROM (
                            SELECT DISTINCT _person_id as person_id,
                                            DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') AS "day"
                            FROM ({events}) posthog_event
                            {action_join}
                            JOIN
                            (SELECT person_id as _person_id,
                                    distinct_id
                                FROM posthog_persondistinctid
                                WHERE team_id = %(team_id)s) pdi on posthog_event.distinct_id = pdi.distinct_id
                            WHERE team_id = %(team_id)s
                            AND {event_condition}
                            GROUP BY _person_id, day
                            HAVING DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') >=
                                %(prev_date_from)s
                            AND DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') <=
                                %(date_to)s
                        ) base
                GROUP BY person_id
                UNION ALL
                SELECT person_id, base_day, subsequent_day
                FROM (
                            SELECT *
                            FROM (
                                    SELECT *,
                                            LAG(person_id, 1) OVER ( ORDER BY person_id)    lag_id,
                                            LAG(subsequent_day, 1) OVER ( ORDER BY person_id) lag_day
                                    FROM (
                                            SELECT person_id, total as base_day, day_start as subsequent_day
                                            FROM (
                                                    SELECT DISTINCT _person_id as person_id,
                                                                    array_agg(date_trunc(%(interval)s, posthog_event.timestamp)) as day
                                                    FROM ({events}) posthog_event
                                                    {action_join}
                                                    JOIN
                                                    (SELECT person_id as _person_id,
                                                            distinct_id
                                                        FROM posthog_persondistinctid
                                                        WHERE team_id = %(team_id)s) pdi on posthog_event.distinct_id = pdi.distinct_id
                                                    WHERE team_id = %(team_id)s
                                                        AND {event_condition}
                                                        AND posthog_event.timestamp <= %(after_date_to)s
                                                        AND DATE_TRUNC(%(interval)s, "posthog_event"."timestamp" AT TIME ZONE 'UTC') >=
                                                            %(date_from)s
                                                    GROUP BY _person_id
                                                ) as e
                                                    CROSS JOIN (
                                                SELECT to_timestamp('0000-00-00 00:00:00', 'YYYY-MM-DD HH24:MI:SS') AS total,
                                                        DATE_TRUNC(%(interval)s,
                                                                    %(after_date_to)s -
                                                                    n * INTERVAL %(one_interval)s) as day_start
                                                FROM generate_series(1, %(num_intervals)s) as n
                                            ) as b
                                            WHERE day_start != ALL (day)
                                            ORDER BY person_id, subsequent_day ASC
                                        ) dormant_days
                                        ORDER BY person_id, subsequent_day ASC
                                ) lagged
                            WHERE ((lag_id IS NULL OR lag_id != lagged.person_id) AND subsequent_day != DATE_TRUNC(%(interval)s, %(date_from)s + INTERVAL %(one_interval)s - INTERVAL %(sub_interval)s))
                            OR (lag_id = lagged.person_id AND lag_day < subsequent_day - INTERVAL %(one_interval)s)
                        ) dormant_days
            ) e
                JOIN (
            SELECT DISTINCT _person_id as person_id,
                            DATE_TRUNC(%(interval)s,
                                        min("posthog_event"."timestamp") AT TIME ZONE 'UTC') earliest
            FROM ({earliest_events}) posthog_event
            JOIN
            (SELECT person_id as _person_id,
                    distinct_id
                FROM posthog_persondistinctid
                WHERE team_id = %(team_id)s) pdi on posthog_event.distinct_id = pdi.distinct_id
            {action_join}
            WHERE team_id = %(team_id)s
                AND {event_condition}
            GROUP BY _person_id
        ) earliest ON e.person_id = earliest.person_id
    ) e
    WHERE status = %(status)s
    AND DATE_TRUNC(%(interval)s, %(target_date)s) = subsequent_day
    LIMIT %(limit)s OFFSET %(offset)s
"""


def get_interval(period: str) -> Union[timedelta, relativedelta]:
    if period == "minute":
        return timedelta(minutes=1)
    elif period == "hour":
        return timedelta(hours=1)
    elif period == "day":
        return timedelta(days=1)
    elif period == "week":
        return timedelta(weeks=1)
    elif period == "month":
        return relativedelta(months=1)
    else:
        raise ValidationError("{} not supported".format(period))


def get_time_diff(
    interval: str, start_time: Optional[datetime], end_time: Optional[datetime], team_id: int
) -> Tuple[int, datetime, datetime, datetime, datetime]:

    _start_time = start_time or Event.objects.filter(team_id=team_id).order_by("timestamp")[0].timestamp.replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    _end_time = end_time or timezone.now()

    interval_diff = get_interval(interval)

    diff = _end_time - _start_time
    addition = 2 if interval == "week" else 1
    return (
        int(diff.total_seconds() / TIME_IN_SECONDS[interval]) + addition,
        _start_time - interval_diff,
        _start_time,
        _end_time,
        _end_time + interval_diff,
    )


def get_trunc_func(period: str) -> Tuple[str, str]:
    if period == "minute":
        return "minute", "second"
    elif period == "hour":
        return "hour", "minute"
    elif period == "day":
        return "day", "hour"
    elif period == "week":
        return "week", "day"
    elif period == "month":
        return "month", "day"
    else:
        raise ValidationError(f"Period {period} is unsupported.")


class LifecycleTrend:
    def _serialize_lifecycle(self, entity: Entity, filter: Filter, team_id: int) -> List[Dict[str, Any]]:

        period = filter.interval
        num_intervals, prev_date_from, date_from, date_to, after_date_to = get_time_diff(
            period, filter.date_from, filter.date_to, team_id
        )
        interval_trunc, sub_interval = get_trunc_func(period=period)

        # include the before and after when filteirng all events

        filter = filter.with_data({"date_from": prev_date_from.isoformat(), "date_to": after_date_to.isoformat()})

        filtered_events = (
            Event.objects.filter(team_id=team_id).add_person_id(team_id).filter(filter_events(team_id, filter, entity))
        )
        event_query, event_params = queryset_to_named_query(filtered_events, "events")

        earliest_events_filtered = (
            Event.objects.filter(team_id=team_id)
            .add_person_id(team_id)
            .filter(filter_events(team_id, filter, entity, include_dates=False))
        )
        earliest_events_query, earliest_events_params = queryset_to_named_query(
            earliest_events_filtered, "earliest_events"
        )

        with connection.cursor() as cursor:
            cursor.execute(
                LIFECYCLE_SQL.format(
                    action_join=ACTION_JOIN if entity.type == TREND_FILTER_TYPE_ACTIONS else "",
                    event_condition="{} = %(event)s".format(
                        "action_id" if entity.type == TREND_FILTER_TYPE_ACTIONS else "event"
                    ),
                    events=event_query,
                    earliest_events=earliest_events_query,
                ),
                {
                    "team_id": team_id,
                    "event": entity.id,
                    "interval": interval_trunc,
                    "one_interval": "1 " + interval_trunc,
                    "sub_interval": "1 " + sub_interval,
                    "num_intervals": num_intervals,
                    "prev_date_from": prev_date_from,
                    "date_from": date_from,
                    "date_to": date_to,
                    "after_date_to": after_date_to,
                    **event_params,
                    **earliest_events_params,
                },
            )
            res = []
            for val in cursor.fetchall():
                label = "{} - {}".format(entity.name, val[2])
                additional_values = {"label": label, "status": val[2]}
                parsed_result = parse_response(val, filter, additional_values)
                res.append(parsed_result)
        return res

    def get_people(
        self,
        filter: Filter,
        team_id: int,
        target_date: datetime,
        lifecycle_type: str,
        request: Request,
        limit: int = 100,
    ):
        entity = filter.entities[0]
        period = filter.interval
        num_intervals, prev_date_from, date_from, date_to, after_date_to = get_time_diff(
            period, filter.date_from, filter.date_to, team_id
        )
        interval_trunc, sub_interval = get_trunc_func(period=period)

        # include the before and after when filteirng all events
        filter = filter.with_data({"date_from": prev_date_from.isoformat(), "date_to": after_date_to.isoformat()})

        filtered_events = (
            Event.objects.filter(team_id=team_id).add_person_id(team_id).filter(filter_events(team_id, filter, entity))
        )
        event_query, event_params = queryset_to_named_query(filtered_events)

        earliest_events_filtered = (
            Event.objects.filter(team_id=team_id)
            .add_person_id(team_id)
            .filter(filter_events(team_id, filter, entity, include_dates=False))
        )
        earliest_events_query, earliest_events_params = queryset_to_named_query(
            earliest_events_filtered, "earliest_events"
        )

        with connection.cursor() as cursor:
            cursor.execute(
                LIFECYCLE_PEOPLE_SQL.format(
                    action_join=ACTION_JOIN if entity.type == TREND_FILTER_TYPE_ACTIONS else "",
                    event_condition="{} = %(event)s".format(
                        "action_id" if entity.type == TREND_FILTER_TYPE_ACTIONS else "event"
                    ),
                    events=event_query,
                    earliest_events=earliest_events_query,
                ),
                {
                    "team_id": team_id,
                    "event": entity.id,
                    "interval": interval_trunc,
                    "one_interval": "1 " + interval_trunc,
                    "sub_interval": "1 " + sub_interval,
                    "num_intervals": num_intervals,
                    "prev_date_from": prev_date_from,
                    "date_from": date_from,
                    "date_to": date_to,
                    "after_date_to": after_date_to,
                    "target_date": target_date,
                    "status": lifecycle_type,
                    "offset": filter.offset,
                    "limit": limit,
                    **event_params,
                    **earliest_events_params,
                },
            )
            pids = cursor.fetchall()

            people = Person.objects.filter(team_id=team_id, id__in=[p[0] for p in pids],)
            from posthog.api.person import PersonSerializer

            people = filter_persons(team_id, request, people)  # type: ignore
            people = people.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))

            return PersonSerializer(people, many=True).data


def parse_response(stats: Dict, filter: Filter, additional_values: Dict = {}) -> Dict[str, Any]:
    counts = stats[1]
    dates = [
        ((item - timedelta(days=1)) if filter.interval == "month" else item).strftime(
            "%Y-%m-%d{}".format(", %H:%M" if filter.interval == "hour" or filter.interval == "minute" else "")
        )
        for item in stats[0]
    ]
    labels = [
        ((item - timedelta(days=1)) if filter.interval == "month" else item).strftime(
            "%-d-%b-%Y{}".format(" %H:%M" if filter.interval == "hour" or filter.interval == "minute" else "")
        )
        for item in stats[0]
    ]
    days = [
        ((item - timedelta(days=1)) if filter.interval == "month" else item).strftime(
            "%Y-%m-%d{}".format(" %H:%M:%S" if filter.interval == "hour" or filter.interval == "minute" else "")
        )
        for item in stats[0]
    ]
    return {
        "data": counts,
        "count": sum(counts),
        "dates": dates,
        "labels": labels,
        "days": days,
        **additional_values,
    }
