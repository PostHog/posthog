from django.db import models, transaction
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
from django.contrib.postgres.fields import JSONField
from django.utils import timezone

from .element_group import ElementGroup
from .element import Element
from .action import Action, ActionStep
from .person import PersonDistinctId, Person
from .team import Team

from posthog.tasks.slack import post_event_to_slack
from typing import Dict, Union, List, Optional, Any

import re

attribute_regex = r"([a-zA-Z]*)\[(.*)=[\'|\"](.*)[\'|\"]\]"


def split_selector_into_parts(selector: str) -> List:
    tags = selector.split(" > ")
    tags.reverse()
    ret: List[Dict[str, Union[str, List]]] = []
    for tag in tags:
        data: Dict[str, Union[str, List]] = {}
        result = re.search(attribute_regex, tag)
        if result and "[id=" in tag:
            data["attr_id"] = result[3]
            tag = result[1]
        if result and "[" in tag:
            data["attributes__{}".format(result[2])] = result[3]
            tag = result[1]
        if "nth-child(" in tag:
            parts = tag.split(":nth-child(")
            data["nth_child"] = parts[1].replace(")", "")
            tag = parts[0]
        if "." in tag:
            parts = tag.split(".")
            data["attr_class"] = parts[1:]
            tag = parts[0]
        if tag:
            data["tag_name"] = tag
        ret.append(data)
    return ret


class EventManager(models.QuerySet):
    def filter_by_element(self, action_step):
        groups = ElementGroup.objects.filter(team=action_step.action.team_id)
        filter = {}
        for key in ["tag_name", "text", "href"]:
            if getattr(action_step, key):
                filter["element__{}".format(key)] = getattr(action_step, key)

        if action_step.selector:
            parts = split_selector_into_parts(action_step.selector)
            subqueries = {}
            for index, tag in enumerate(parts):
                if tag.get("attr_class"):
                    attr_class = tag.pop("attr_class")
                    tag["attr_class__contains"] = attr_class
                subqueries["match_{}".format(index)] = Subquery(
                    Element.objects.filter(group_id=OuterRef("pk"), **tag).values(
                        "order"
                    )[:1]
                )
            groups = groups.annotate(**subqueries)  # type: ignore
            for index, _ in enumerate(parts):
                filter["match_{}__isnull".format(index)] = False
                if index > 0:
                    filter["match_{}__gt".format(index)] = F(
                        "match_{}".format(index - 1)
                    )  # make sure the ordering of the elements is correct

        if not filter:
            return {}
        groups = groups.filter(**filter)
        return {"elements_hash__in": groups.values_list("hash", flat=True)}

    def filter_by_url(self, action_step):
        if not action_step.url:
            return {}
        if action_step.url_matching == ActionStep.EXACT:
            return {"properties__$current_url": action_step.url}
        return {"properties__$current_url__icontains": action_step.url}

    def filter_by_event(self, action_step):
        if not action_step.event:
            return {}
        return {"event": action_step.event}

    def add_person_id(self, team_id: str):
        return self.annotate(
            person_id=Subquery(
                PersonDistinctId.objects.filter(
                    team_id=team_id, distinct_id=OuterRef("distinct_id")
                )
                .order_by()
                .values("person_id")[:1]
            )
        )

    def query_db_by_action(self, action, order_by="-timestamp") -> models.QuerySet:
        events = self
        any_step = Q()
        steps = action.steps.all()
        if len(steps) == 0:
            return self.none()

        for step in steps:
            any_step |= Q(
                **self.filter_by_element(step),
                **self.filter_by_url(step),
                **self.filter_by_event(step)
            )
        events = self.filter(team_id=action.team_id).filter(any_step)

        if order_by:
            events = events.order_by(order_by)

        return events

    def filter_by_action(self, action, order_by="-id") -> models.QuerySet:
        events = self.filter(action=action).add_person_id(team_id=action.team_id)
        if order_by:
            events = events.order_by(order_by)
        return events

    def filter_by_event_with_people(
        self, event, team_id, order_by="-id"
    ) -> models.QuerySet:
        events = (
            self.filter(team_id=team_id)
            .filter(event=event)
            .add_person_id(team_id=team_id)
        )
        if order_by:
            events = events.order_by(order_by)
        return events

    def create(self, site_url: Optional[str] = None, *args: Any, **kwargs: Any):
        with transaction.atomic():
            if kwargs.get("elements"):
                if kwargs.get("team"):
                    kwargs["elements_hash"] = ElementGroup.objects.create(
                        team=kwargs["team"], elements=kwargs.pop("elements")
                    ).hash
                else:
                    kwargs["elements_hash"] = ElementGroup.objects.create(
                        team_id=kwargs["team_id"], elements=kwargs.pop("elements")
                    ).hash
            event = super().create(*args, **kwargs)
            should_post_to_slack = False
            relations = []
            for action in event.actions:
                relations.append(
                    action.events.through(action_id=action.pk, event=event)
                )
                if action.post_to_slack:
                    should_post_to_slack = True

            Action.events.through.objects.bulk_create(relations, ignore_conflicts=True)

            if (
                should_post_to_slack
                and event.team
                and event.team.slack_incoming_webhook
            ):
                post_event_to_slack.delay(event.id, site_url)

            return event


class Event(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=["elements_hash"]),
            models.Index(fields=["timestamp", "team_id", "event"]),
        ]

    @property
    def person(self):
        return Person.objects.get(
            team_id=self.team_id, persondistinctid__distinct_id=self.distinct_id
        )

    # This (ab)uses query_db_by_action to find which actions match this event
    # We can't use filter_by_action here, as we use this function when we create an event so
    # the event won't be in the Action-Event relationship yet.
    @property
    def actions(self) -> List:
        actions = (
            Action.objects.filter(team_id=self.team_id, steps__event=self.event)
            .distinct("id")
            .prefetch_related(
                Prefetch("steps", queryset=ActionStep.objects.order_by("id"))
            )
        )
        events: models.QuerySet[Any] = Event.objects.filter(pk=self.pk)
        for action in actions:
            events = events.annotate(
                **{
                    "action_{}".format(action.pk): Event.objects.filter(pk=self.pk)
                    .query_db_by_action(action)
                    .values("id")[:1]
                }
            )
        event = [event for event in events][0]

        return [
            action
            for action in actions
            if getattr(event, "action_{}".format(action.pk))
        ]

    objects: EventManager = EventManager.as_manager()  # type: ignore
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    event: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    distinct_id: models.CharField = models.CharField(max_length=200)
    properties: JSONField = JSONField(default=dict)
    elements: JSONField = JSONField(default=list, null=True, blank=True)
    timestamp: models.DateTimeField = models.DateTimeField(
        default=timezone.now, blank=True
    )
    elements_hash: models.CharField = models.CharField(
        max_length=200, null=True, blank=True
    )
