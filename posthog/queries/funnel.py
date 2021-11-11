import re
import uuid
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional

import pytz
from django.db import connection
from django.db.models import IntegerField, Min, Value
from django.utils import timezone
from psycopg2 import sql

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS, TRENDS_LINEAR
from posthog.models import Entity, Event, Filter, Person, Team
from posthog.models.utils import namedtuplefetchall, sane_repr
from posthog.queries.base import BaseQuery, properties_to_Q
from posthog.utils import format_label_date, get_daterange


class Funnel(BaseQuery):

    _filter: Filter
    _team: Team

    def __init__(self, filter: Filter, team: Team) -> None:
        self._filter = filter
        self._team = team

    def _gen_lateral_bodies(self, within_time: Optional[str] = None):
        annotations = {}
        for index, step in enumerate(self._filter.entities):
            filter_key = "event" if step.type == TREND_FILTER_TYPE_EVENTS else "action__pk"
            event = (
                Event.objects.values("distinct_id")
                .annotate(step_ts=Min("timestamp"), person_id=Value("99999999", IntegerField()),)
                .filter(
                    self._filter.date_filter_Q,
                    **{filter_key: step.id},
                    team_id=self._team.pk,
                    **({"distinct_id": "1234321"} if index > 0 else {}),
                    **(
                        {
                            "timestamp__gte": timezone.now().replace(
                                year=2000, month=1, day=1, hour=0, minute=0, second=0, microsecond=0
                            )
                        }
                        if index > 0
                        else {}
                    ),
                )
                .filter(properties_to_Q(self._filter.properties, team_id=self._team.pk,))
                .filter(properties_to_Q(step.properties, team_id=self._team.pk))
            )
            with connection.cursor() as cursor:
                event_string = cursor.mogrify(*event.query.sql_with_params())
            # Replace placeholders injected by the Django ORM
            # We do this because the Django ORM doesn't easily allow us to parameterize sql identifiers
            # This is probably the most hacky part of the entire query generation
            event_string = (
                event_string.decode("utf-8")
                .replace("'1234321'", "{prev_step_person_id}")
                .replace(
                    "'2000-01-01T00:00:00+00:00'::timestamptz",
                    "{prev_step_ts} %s"
                    % (
                        ' AND "posthog_event"."timestamp" < "step_{}"."step_ts" + {}'.format(index - 1, within_time)
                        if within_time
                        else ""
                    ),
                )
                .replace('"posthog_event"."distinct_id"', '"pdi"."person_id"')
                .replace("99999999", '"pdi"."person_id"')
                .replace(', "pdi"."person_id" AS "person_id"', "")
            )
            event_string = re.sub(
                # accommodate for identifier e.g. W0 so that it still ends up right after `FROM posthog_event`
                # not after `ON pdi.distinct_id = posthog_event.distinct_id`
                r'FROM "posthog_event"( [A-Z][0-9])?',
                r"FROM posthog_event\1 JOIN posthog_persondistinctid pdi "
                #  NOTE: here we are joining on the unique identifier of the
                #  persondistinctid table, i.e. (team_id, distinct_id)
                r"ON pdi.distinct_id = posthog_event.distinct_id AND pdi.team_id = posthog_event.team_id",
                event_string,
            )
            query = sql.SQL(event_string)
            annotations["step_{}".format(index)] = query
        return annotations

    def _serialize_step(self, step: Entity, count: int, people: Optional[List[uuid.UUID]] = None) -> Dict[str, Any]:
        if step.type == TREND_FILTER_TYPE_ACTIONS:
            name = step.get_action().name
        else:
            name = step.id
        return {
            "action_id": step.id,
            "name": name,
            "custom_name": step.custom_name,
            "order": step.order,
            "people": people if people else [],
            "count": count,
            "type": step.type,
        }

    def _build_query(self, within_time: Optional[str] = None):
        """Build query using lateral joins using a combination of Django generated SQL
        and sql built using psycopg2
        """
        query_bodies = self._gen_lateral_bodies(within_time=within_time)

        ON_TRUE = "ON TRUE"
        LEFT_JOIN_LATERAL = "LEFT JOIN LATERAL"
        LAT_JOIN_BODY = (
            """({query}) {step} {on_true} {join}""" if len(query_bodies) > 1 else """({query}) {step} {on_true} """
        )

        steps = [sql.Identifier(step) for step, _ in query_bodies.items()]
        select_steps = [
            sql.Composed([step, sql.SQL("."), sql.Identifier("step_ts"), sql.SQL(" as "), step,]) for step in steps
        ]
        lateral_joins = []
        i = 0
        for step, qb in query_bodies.items():
            if i > 0:
                # For each step after the first we must reference the previous step's person_id and step_ts
                q = qb.format(
                    prev_step_person_id=sql.Composed([steps[i - 1], sql.SQL("."), sql.Identifier("person_id")]),
                    prev_step_ts=sql.Composed([steps[i - 1], sql.SQL("."), sql.Identifier("step_ts")]),
                )

            if i == 0:
                # Generate first lateral join body
                # The join conditions are different for first, middles, and last
                # For the first step we include the alias, lateral join, but not 'ON TRUE'
                base_body = sql.SQL(LAT_JOIN_BODY).format(
                    query=qb, step=sql.SQL(step), on_true=sql.SQL(""), join=sql.SQL(LEFT_JOIN_LATERAL),
                )
            elif i == len(query_bodies) - 1:
                # Generate last lateral join body
                # The join conditions are different for first, middles, and last
                # For the last step we include the alias, 'ON TRUE', but not another `LATERAL JOIN`
                base_body = sql.SQL(LAT_JOIN_BODY).format(
                    query=q, step=sql.SQL(step), on_true=sql.SQL(ON_TRUE), join=sql.SQL(""),
                )
            else:
                # Generate middle lateral join body
                # The join conditions are different for first, middles, and last
                # For the middle steps we include the alias, 'ON TRUE', and `LATERAL JOIN`
                base_body = sql.SQL(LAT_JOIN_BODY).format(
                    query=q, step=sql.SQL(step), on_true=sql.SQL(ON_TRUE), join=sql.SQL(LEFT_JOIN_LATERAL),
                )
            lateral_joins.append(base_body)
            i += 1

        event_chain_query = sql.SQL(" ").join(lateral_joins).as_string(connection.connection)

        query = f"""
            SELECT
                DISTINCT ON (person.id)
                person.uuid,
                person.created_at,
                person.team_id,
                person.properties,
                person.is_user_id,
                {sql.SQL(",").join(select_steps).as_string(connection.connection)}
            FROM posthog_person person
            JOIN posthog_persondistinctid pdi ON pdi.person_id = person.id
            JOIN {event_chain_query}
            -- join on person_id for the first event.
            -- NOTE: there is some implicit coupling here in that I am
            -- assuming the name of the first event select is "step_0".
            -- Maybe worth cleaning up in the future
            ON person.id = step_0.person_id
            WHERE person.team_id = {self._team.pk} AND person.id IS NOT NULL
            ORDER BY person.id, step_0.step_ts ASC
        """
        return query

    def _build_trends_query(self, filter: Filter) -> sql.SQL:
        # TODO: Only select from_step and to_step in _build_steps_query
        particular_steps = (
            sql.SQL(f'COUNT("step_{index}") as "step_{index}_count"') for index in range(len(filter.entities))
        )
        trends_query = sql.SQL(
            """
            SELECT
                date_trunc({interval}, {interval_field}) as "date",
                {particular_steps}
            FROM (
                {steps_query}
            ) steps_at_dates GROUP BY "date"
        """
        ).format(
            interval=sql.Literal(filter.interval),
            particular_steps=sql.SQL(",\n").join(particular_steps),
            steps_query=sql.SQL(self._build_query(within_time="'1 day'")),
            interval_field=sql.SQL("step_0")
            if filter.interval != "week"
            else sql.SQL("(\"step_0\" + interval '1 day') AT TIME ZONE 'UTC'"),
        )
        return trends_query

    def _get_last_step_attr(self, step: object) -> int:
        if len(self._filter.entities) == 1:
            return 0
        return getattr(step, "step_{}_count".format(len(self._filter.entities) - 1))

    def _get_trends(self) -> List[Dict[str, Any]]:
        serialized: Dict[str, Any] = {"count": 0, "data": [], "days": [], "labels": []}
        with connection.cursor() as cursor:
            qstring = self._build_trends_query(self._filter).as_string(cursor.connection)
            cursor.execute(qstring)
            steps_at_dates = namedtuplefetchall(cursor)

        date_range = get_daterange(
            self._filter.date_from or steps_at_dates[0].date, self._filter.date_to, frequency=self._filter.interval
        )

        data_array = [
            {"date": step.date, "count": round(self._get_last_step_attr(step) / step.step_0_count * 100)}
            for step in steps_at_dates
        ]

        if self._filter.interval == "week":
            for df in data_array:
                df["date"] -= timedelta(days=df["date"].weekday() + 1)
        elif self._filter.interval == "month":
            for df in data_array:
                df["date"] = df["date"].replace(day=1)
        for df in data_array:
            df["date"] = df["date"].replace(tzinfo=pytz.utc).isoformat()

        datewise_data = {d["date"]: d["count"] for d in data_array}
        values = [(key, datewise_data.get(key.isoformat(), 0)) for key in date_range]

        for item in values:
            serialized["days"].append(item[0])
            serialized["data"].append(item[1])
            serialized["labels"].append(format_label_date(item[0], self._filter.interval))
        return [serialized]

    def data_to_return(self, results: List[Person]) -> List[Dict[str, Any]]:
        steps = []

        average_time: Dict[int, Dict[str, Any]] = {}
        for index, funnel_step in enumerate(self._filter.entities, start=0):
            if index != 0:
                average_time[index] = {"total_time": timedelta(0), "total_people": 0}

        person_score: Dict = defaultdict(int)
        for index, funnel_step in enumerate(self._filter.entities):
            relevant_people = []
            for person in results:
                if (
                    index > 0
                    and getattr(person, "step_{}".format(index))
                    and getattr(person, "step_{}".format(index - 1))
                ):
                    average_time[index]["total_time"] += getattr(person, "step_{}".format(index)) - getattr(
                        person, "step_{}".format(index - 1)
                    )
                    average_time[index]["total_people"] += 1

                if getattr(person, "step_{}".format(index)):
                    person_score[person.uuid] += 1
                    relevant_people.append(person.uuid)
            steps.append(
                self._serialize_step(funnel_step, len(relevant_people) if relevant_people else 0, relevant_people)
            )

        if len(steps) > 0:
            for index, _ in enumerate(steps):
                steps[index]["people"] = sorted(steps[index]["people"], key=lambda p: person_score[p], reverse=True)[
                    0:100
                ]

        for index in average_time.keys():
            steps[index - 1]["average_time"] = (
                (average_time[index]["total_time"].total_seconds() / average_time[index]["total_people"])
                if average_time[index]["total_people"] > 0
                else 0
            )

        return steps

    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        """
        Builds and runs a query to get all persons that have been in the funnel
        steps defined by `self._filter.entities`. For example, entities may be
        defined as:

            1. event with event name "user signed up"
            2. event with event name "user looked at report"

        For a person to match they have to have gone through all `entities` in
        order. We also only return one such chain of entities, the earliest one
        we find.
        """

        # If no steps are defined, then there's no point in querying the database
        if len(self._filter.entities) == 0:
            return []

        if self._filter.display == TRENDS_LINEAR:
            return self._get_trends()

        with connection.cursor() as cursor:
            # Then we build a query to query for them in order
            qstring = self._build_query(within_time=None)

            cursor.execute(qstring)
            results = namedtuplefetchall(cursor)
        return self.data_to_return(results)

    __repr__ = sane_repr("_team", "_filter")
