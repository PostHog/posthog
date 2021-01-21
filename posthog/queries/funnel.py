from posthog.queries.trends import FREQ_MAP
from posthog.utils import append_data
import pandas as pd
import re
import uuid
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.db import connection
from django.db.models import IntegerField, Min, Value
from django.utils import timezone
from psycopg2 import sql

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.models import Action, Entity, Event, Filter, Person, Team
from posthog.models.utils import namedtuplefetchall
from posthog.queries.base import BaseQuery, properties_to_Q


class Funnel(BaseQuery):

    _filter: Filter
    _team: Team

    def __init__(self, filter: Filter, team: Team) -> None:
        self._filter = filter
        self._team = team

    def _gen_lateral_bodies(self):
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
                .filter(properties_to_Q(self._filter.properties, team_id=self._team.pk))
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
                .replace("'2000-01-01T00:00:00+00:00'::timestamptz", "{prev_step_ts}")
                .replace('"posthog_event"."distinct_id"', '"pdi"."person_id"')
                .replace("99999999", '"pdi"."person_id"')
                .replace(', "pdi"."person_id" AS "person_id"', "")
            )
            event_string = re.sub(
                # accommodate for identifier e.g. W0 so that it still ends up right after `FROM posthog_event`
                # not after `ON pdi.distinct_id = posthog_event.distinct_id`
                r'FROM "posthog_event"( [A-Z][0-9])?',
                r"FROM posthog_event\1 JOIN posthog_persondistinctid pdi "
                r"ON pdi.distinct_id = posthog_event.distinct_id",
                event_string,
            )
            query = sql.SQL(event_string)
            annotations["step_{}".format(index)] = query
        return annotations

    def _serialize_step(self, step: Entity, count: int, people: Optional[List[uuid.UUID]] = None) -> Dict[str, Any]:
        if step.type == TREND_FILTER_TYPE_ACTIONS:
            name = Action.objects.get(team=self._team.pk, pk=step.id).name
        else:
            name = step.id
        return {
            "action_id": step.id,
            "name": name,
            "order": step.order,
            "people": people if people else [],
            "count": count,
            "type": step.type,
        }

    def _build_query(self, query_bodies: dict):
        """Build query using lateral joins using a combination of Django generated SQL
           and sql built using psycopg2
        """

        ON_TRUE = "ON TRUE"
        LEFT_JOIN_LATERAL = "LEFT JOIN LATERAL"
        QUERY_HEADER = "SELECT {people}, {fields} FROM "
        LAT_JOIN_BODY = (
            """({query}) {step} {on_true} {join}""" if len(query_bodies) > 1 else """({query}) {step} {on_true} """
        )
        PERSON_FIELDS = [
            [sql.Identifier("posthog_person"), sql.Identifier("uuid")],
            [sql.Identifier("posthog_person"), sql.Identifier("created_at")],
            [sql.Identifier("posthog_person"), sql.Identifier("team_id")],
            [sql.Identifier("posthog_person"), sql.Identifier("properties")],
            [sql.Identifier("posthog_person"), sql.Identifier("is_user_id")],
        ]
        QUERY_FOOTER = sql.SQL(
            """
            JOIN posthog_person ON posthog_person.id = {step0}.person_id
            WHERE {step0}.person_id IS NOT NULL
            GROUP BY {group_by}"""
        )

        person_fields = sql.SQL(",").join([sql.SQL(".").join(col) for col in PERSON_FIELDS])

        steps = [sql.Identifier(step) for step, query in query_bodies.items()]
        select_steps = [
            sql.Composed([sql.SQL("MIN("), step, sql.SQL("."), sql.Identifier("step_ts"), sql.SQL(") as "), step,])
            for step in steps
        ]
        lateral_joins = []
        query = sql.SQL(QUERY_HEADER).format(fields=sql.SQL(",").join(select_steps), people=person_fields)
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
        query_footer = QUERY_FOOTER.format(step0=steps[0], group_by=person_fields)
        query = query + sql.SQL(" ").join(lateral_joins) + query_footer
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
            steps_query=self._build_query(self._gen_lateral_bodies()),
            interval_field=sql.SQL("step_0") if filter.interval != 'week' else sql.SQL("(\"step_0\" + interval '1 day') AT TIME ZONE 'UTC'")
        )
        return trends_query

    def _serialize_trends(self, filter: Filter, *, from_step: int, to_step: int) -> Dict[str, Any]:
        serialized: Dict[str, Any] = {
            "count": 0,
            "data": [],
            "days": [],
        }
        with connection.cursor() as cursor:
            qstring = self._build_trends_query(filter).as_string(cursor.connection)
            print(qstring)
            cursor.execute(qstring)
            steps_at_dates = namedtuplefetchall(cursor)
        conversion_over_date_df = pd.DataFrame(
            data=[row[to_step + 1] for row in steps_at_dates],
            index=[row[0] for row in steps_at_dates],
            columns=["conversion_percentage"],
            dtype=float,
        )  # +1 because date takes up 0th index
        conversion_over_date_df.index.name = "date"
        conversion_over_date_df["conversion_percentage"] = round(
            conversion_over_date_df["conversion_percentage"] / [row[from_step + 1] for row in steps_at_dates] * 100, 1
        )
        import ipdb; ipdb.set_trace()
        time_index = pd.date_range(
            filter.date_from - pd.offsets.MonthBegin(), filter.date_to, freq=FREQ_MAP[filter.interval]
        )
        conversion_over_date_df = conversion_over_date_df.reindex(time_index, fill_value=0.0)
        serialized.update(append_data(conversion_over_date_df.itertuples(), filter.interval, math=None))
        return serialized

    def get_trends(self, *, from_step: Optional[int] = None, to_step: Optional[int] = None) -> List[Dict[str, Any]]:
        if (from_step is None) ^ (to_step is None):
            raise ValueError("Either both or neither from_step and to_step must be specified.")

        if from_step is not None and to_step is not None:
            try:
                from_step = int(from_step)
                to_step = int(to_step)
            except ValueError:
                raise ValueError("Parameters from_step and to_step must be valid integers.")

        if from_step is None:
            from_step = 0
            to_step = len(self._filter.entities) - 1

        return [self._serialize_trends(self._filter, from_step=from_step, to_step=to_step)]

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
        with connection.cursor() as cursor:
            qstring = self._build_query(self._gen_lateral_bodies()).as_string(cursor.connection)
            cursor.execute(qstring)
            results = namedtuplefetchall(cursor)
        return self.data_to_return(results)
