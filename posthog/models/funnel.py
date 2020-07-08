from collections import defaultdict
import re

from django.db import models
from django.contrib.postgres.fields import JSONField, ArrayField
from django.db import connection
from django.db.models import (
    Exists,
    Min,
    OuterRef,
    Q,
    Subquery,
    F,
    signals,
    Prefetch,
    IntegerField,
    Value,
    QuerySet,
)
from typing import List, Dict, Any, Optional

from psycopg2 import sql  # type: ignore

from .event import Event
from .action import Action
from .filter import Filter
from .entity import Entity
from .utils import namedtuplefetchall

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS


class Funnel(models.Model):
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    filters: JSONField = JSONField(default=dict)

    def _gen_lateral_bodies(self, team_id: int, filter: Filter):
        annotations = {}
        for index, step in enumerate(filter.entities):
            filter_key = "event" if step.type == TREND_FILTER_TYPE_EVENTS else "action__pk"
            event = (
                Event.objects.values("distinct_id")
                .annotate(step_ts=Min("timestamp"), person_id=Value("99999999", IntegerField()),)
                .filter(
                    filter.date_filter_Q,
                    **{filter_key: step.id},
                    team_id=team_id,
                    **({"distinct_id": "1234321"} if index > 0 else {}),
                    **({"timestamp__gte": "2000-01-01"} if index > 0 else {}),
                )
                .filter(filter.properties_to_Q(team_id=team_id))
                .filter(step.properties_to_Q(team_id=team_id))
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

    def _serialize_step(self, step: Entity, people: Optional[List[int]] = None) -> Dict[str, Any]:
        if step.type == TREND_FILTER_TYPE_ACTIONS:
            name = Action.objects.get(team=self.team_id, pk=step.id).name
        else:
            name = step.id
        return {
            "action_id": step.id,
            "name": name,
            "order": step.order,
            "people": people if people else [],
            "count": len(people) if people else 0,
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
            [sql.Identifier("posthog_person"), sql.Identifier("id")],
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

    def get_steps(self) -> List[Dict[str, Any]]:
        filter = Filter(data=self.filters)
        with connection.cursor() as cursor:
            qstring = self._build_query(self._gen_lateral_bodies(team_id=self.team_id, filter=filter)).as_string(
                cursor.connection
            )
            cursor.execute(qstring)
            people = namedtuplefetchall(cursor)
        steps = []

        person_score: Dict = defaultdict(int)
        for index, funnel_step in enumerate(filter.entities):
            relevant_people = []
            for person in people:
                if getattr(person, "step_{}".format(index)):
                    person_score[person.id] += 1
                    relevant_people.append(person.id)
            steps.append(self._serialize_step(funnel_step, relevant_people))

        if len(steps) > 0:
            for index, _ in enumerate(steps):
                steps[index]["people"] = sorted(steps[index]["people"], key=lambda p: person_score[p], reverse=True)[
                    0:100
                ]
        return steps
