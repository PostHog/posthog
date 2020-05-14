from django.db import models
from django.contrib.postgres.fields import JSONField, ArrayField

from django.db.models import (
    Exists,
    OuterRef,
    Q,
    Subquery,
    F,
    signals,
    Prefetch,
    QuerySet,
)
from typing import List, Dict, Any, Optional
import datetime

from .event import Event
from .person import PersonDistinctId
from .action import Action
from .person import Person
from .filter import Filter
from .entity import Entity

from posthog.utils import request_to_date_query
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

    def get_steps(self) -> List[Dict[str, Any]]:
        filter = Filter(data=self.filters)
        people = (
            Person.objects.all()
            .filter(team_id=self.team_id, persondistinctid__distinct_id__isnull=False)
            .annotate(
                **self._annotate_steps(
                    team_id=self.team_id,
                    filter=filter
                )
            )
            .filter(step_0__isnull=False)
            .distinct("pk")
        )

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