from collections import namedtuple

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
    QuerySet,
)
from typing import List, Dict, Any, Optional

from psycopg2 import sql

from .event import Event
from .person import PersonDistinctId
from .action import Action
from .person import Person
from .filter import Filter
from .entity import Entity

from posthog.utils import properties_to_Q, request_to_date_query
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS


class Funnel(models.Model):
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_by: models.ForeignKey = models.ForeignKey(
        "User", on_delete=models.CASCADE, null=True, blank=True
    )
    deleted: models.BooleanField = models.BooleanField(default=False)
    filters: JSONField = JSONField(default=dict)

    def _order_people_in_step(
        self, steps: List[Dict[str, Any]], people: List[int]
    ) -> List[int]:
        def order(person):
            score = 0
            for step in steps:
                if person in step["people"]:
                    score += 1
            return (score, person)

        return sorted(people, key=order, reverse=True)

    def _annotate_steps(
        self,
        team_id: int,
        filter: Filter
    ) -> Dict[str, Subquery]:
        annotations = {}
        for index, step in enumerate(filter.entities):
            filter_key = (
                "event"
                if step.type == TREND_FILTER_TYPE_EVENTS
                else "action__pk"
            )
            annotations["step_{}".format(index)] = Subquery(
                Event.objects.all()
                .annotate(person_id=OuterRef("id"))
                .filter(
                    filter.date_filter_Q,
                    **{filter_key: step.id},
                    team_id=team_id,
                    distinct_id__in=Subquery(
                        PersonDistinctId.objects.filter(
                            team_id=team_id, person_id=OuterRef("person_id")
                        ).values("distinct_id")
                    ),
                    **(
                        {"timestamp__gt": OuterRef("step_{}".format(index - 1))}
                        if index > 0
                        else {}
                    ),
                )
                .filter(filter.properties_to_Q())
                .filter(step.properties_to_Q())
                .order_by("timestamp")
                .values("timestamp")[:1]
            )
        return annotations

    def _gen_lateral_bodies(
        self,
        team_id,
        filter
    ):
        annotations = {}
        for index, step in enumerate(filter.entities):
            filter_key = (
                "event"
                if step.type == TREND_FILTER_TYPE_EVENTS
                else "action__pk"
            )
            annotations["step_{}".format(index)] = Event.objects.values("distinct_id")\
                .annotate(step_ts=Min("timestamp"))\
                .filter(
                    filter.date_filter_Q,
                    **{filter_key: step.id},
                    team_id=team_id,
                    **(
                        {"distinct_id": "{prev_step_distinct_id}"}
                        if index > 0
                        else {}
                    ),
                ).filter(filter.properties_to_Q())\
                .filter(step.properties_to_Q())
        return annotations

    def _serialize_step(
        self, step: Entity, people: Optional[List[int]] = None
    ) -> Dict[str, Any]:
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

    def namedtuplefetchall(self, cursor):
        "Return all rows from a cursor as a namedtuple"
        desc = cursor.description
        nt_result = namedtuple('Result', [col[0] for col in desc])
        return [nt_result(*row) for row in cursor.fetchall()]

    def _build_query(self, query_bodies: dict):
        ON_TRUE = "ON TRUE"
        LEFT_JOIN_LATERAL = "LEFT JOIN LATERAL"
        QUERY_HEADER = "SELECT {people}, {step}.distinct_id, {fields} FROM "
        LAT_JOIN_BODY = """({query}) {step} {on_true} {join}"""
        PERSON_FIELDS = [[sql.Identifier("posthog_person"), sql.Identifier("id")],
                         [sql.Identifier("posthog_person"), sql.Identifier("created_at")],
                         [sql.Identifier("posthog_person"), sql.Identifier("team_id")],
                         [sql.Identifier("posthog_person"), sql.Identifier("properties")],
                         [sql.Identifier("posthog_person"), sql.Identifier("is_user_id")]]
        QUERY_FOOTER = sql.SQL("""
            JOIN posthog_persondistinctid pdi ON pdi.distinct_id = {step0}.distinct_id
            JOIN posthog_person ON pdi.id = posthog_person.id
            WHERE {step0}.distinct_id IS NOT NULL""")

        person_fields = sql.SQL(",").join([sql.SQL(".").join(col) for col in PERSON_FIELDS])

        steps = [sql.Identifier(step) for step, query in query_bodies.items()]
        select_steps = [sql.Composed([step, sql.SQL("."), sql.Identifier("step_ts"), sql.SQL(" as "), step]) for step in steps]
        lateral_joins = []
        with connection.cursor() as cursor:
            query_bodies = {step: cursor.mogrify(*q.query.sql_with_params()) for step, q in query_bodies.items()}
        query = sql.SQL(QUERY_HEADER).format(
            step=steps[0],
            fields=sql.SQL(',').join(select_steps),
            people=person_fields
        )
        i = 0
        for step, qb in query_bodies.items():
            q = sql.SQL(qb.decode('utf-8').replace("'{", "{").replace("}'", "}"))
            if i == 0:
                base_body = sql.SQL(LAT_JOIN_BODY).format(
                    query=q,
                    step=sql.SQL(step),
                    on_true=sql.SQL(""),
                    join=sql.SQL(LEFT_JOIN_LATERAL)
                )
                lateral_joins.append(base_body)
            elif i == len(query_bodies) - 1:
                q = q.format(prev_step_distinct_id=sql.Composed([steps[i-1], sql.SQL("."), sql.Identifier("distinct_id")]))
                base_body = sql.SQL(LAT_JOIN_BODY).format(
                    query=q,
                    step=sql.SQL(step),
                    on_true=sql.SQL(ON_TRUE),
                    join=sql.SQL("")
                )
                lateral_joins.append(base_body)
            else:
                q = q.format(prev_step_distinct_id=sql.Composed([steps[i-1], sql.SQL("."), sql.Identifier("distinct_id")]))
                base_body = sql.SQL(LAT_JOIN_BODY).format(
                    query=q,
                    step=sql.SQL(step),
                    on_true=sql.SQL(ON_TRUE),
                    join=sql.SQL(LEFT_JOIN_LATERAL)
                )
                lateral_joins.append(base_body)
            i += 1
        query_footer = QUERY_FOOTER.format(
            step0=steps[0]
        )
        query = query + sql.SQL(" ").join(lateral_joins) + query_footer
        return query

    def get_steps(self) -> List[Dict[str, Any]]:
        filter = Filter(data=self.filters)
        with connection.cursor() as cursor:
            qstring = self._build_query(self._gen_lateral_bodies(
                team_id=self.team_id,
                filter=filter)).as_string(cursor.connection)
            print(qstring)
            cursor.execute(qstring)
            people = self.namedtuplefetchall(cursor)
        steps = []
        for index, funnel_step in enumerate(filter.entities):
            relevant_people = [
                person.id
                for person in people
                if getattr(person, "step_{}".format(index))
            ]
            steps.append(self._serialize_step(funnel_step, relevant_people))

        if len(steps) > 0:
            for index, _ in enumerate(steps):
                steps[index]["people"] = self._order_people_in_step(
                    steps, steps[index]["people"]
                )[0:100]
        return steps