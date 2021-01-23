import copy
import datetime
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple, Union

import celery
from django.conf import settings
from django.contrib.postgres.fields import JSONField
from django.db import connection, models, transaction
from django.db.models import Exists, F, OuterRef, Prefetch, Q, QuerySet, Subquery
from django.forms.models import model_to_dict
from django.utils import timezone

from posthog.ee import is_ee_enabled

from .action import Action
from .action_step import ActionStep
from .element import Element
from .element_group import ElementGroup
from .filters import Filter
from .person import Person, PersonDistinctId
from .team import Team
from .utils import namedtuplefetchall

attribute_regex = r"([a-zA-Z]*)\[(.*)=[\'|\"](.*)[\'|\"]\]"


LAST_UPDATED_TEAM_ACTION: Dict[int, datetime.datetime] = {}
TEAM_EVENT_ACTION_QUERY_CACHE: Dict[int, Dict[str, tuple]] = defaultdict(dict)
# TEAM_EVENT_ACTION_QUERY_CACHE looks like team_id -> event ex('$pageview') -> query
TEAM_ACTION_QUERY_CACHE: Dict[int, str] = {}


class SelectorPart(object):
    direct_descendant = False
    unique_order = 0

    def _unescape_class(self, class_name):
        # separate all double slashes "\\" (replace them with "\") and remove all single slashes between them
        return "\\".join([p.replace("\\", "") for p in class_name.split("\\\\")])

    def __init__(self, tag: str, direct_descendant: bool, escape_slashes: bool):
        self.direct_descendant = direct_descendant
        self.data: Dict[str, Union[str, List]] = {}
        self.ch_attributes: Dict[str, Union[str, List]] = {}  # attributes for CH

        result = re.search(attribute_regex, tag)
        if result and "[id=" in tag:
            self.data["attr_id"] = result[3]
            self.ch_attributes["attr_id"] = result[3]
            tag = result[1]
        if result and "[" in tag:
            self.data["attributes__attr__{}".format(result[2])] = result[3]
            self.ch_attributes[result[2]] = result[3]
            tag = result[1]
        if "nth-child(" in tag:
            parts = tag.split(":nth-child(")
            self.data["nth_child"] = parts[1].replace(")", "")
            self.ch_attributes["nth-child"] = self.data["nth_child"]
            tag = parts[0]
        if "." in tag:
            parts = tag.split(".")
            # strip all slashes that are not followed by another slash
            self.data["attr_class__contains"] = [self._unescape_class(p) if escape_slashes else p for p in parts[1:]]
            tag = parts[0]
        if tag:
            self.data["tag_name"] = tag

    @property
    def extra_query(self) -> Dict[str, List[Union[str, List[str]]]]:
        where: List[Union[str, List[str]]] = []
        params: List[Union[str, List[str]]] = []
        for key, value in self.data.items():
            if "attr__" in key:
                where.append("(attributes ->> 'attr__{}') = %s".format(key.split("attr__")[1]))
            else:
                if "__contains" in key:
                    where.append("{} @> %s::varchar(200)[]".format(key.replace("__contains", "")))
                else:
                    where.append("{} = %s".format(key))
            params.append(value)
        return {"where": where, "params": params}


class Selector(object):
    parts: List[SelectorPart] = []

    def __init__(self, selector: str, escape_slashes=True):
        self.parts = []
        # Sometimes people manually add *, just remove them as they don't do anything
        selector = selector.replace("> * > ", "").replace("> *", "")
        tags = re.split(" ", selector.strip())
        tags.reverse()
        for index, tag in enumerate(tags):
            if tag == ">" or tag == "":
                continue
            direct_descendant = False
            if index > 0 and tags[index - 1] == ">":
                direct_descendant = True
            part = SelectorPart(tag, direct_descendant, escape_slashes)
            part.unique_order = len([p for p in self.parts if p.data == part.data])
            self.parts.append(copy.deepcopy(part))


class EventManager(models.QuerySet):
    def _element_subquery(self, selector: Selector) -> Tuple[Dict[str, Subquery], Dict[str, Union[F, bool]]]:
        filter: Dict[str, Union[F, bool]] = {}
        subqueries = {}
        for index, tag in enumerate(selector.parts):
            subqueries["match_{}".format(index)] = Subquery(
                Element.objects.filter(group_id=OuterRef("pk"))
                .values("order")
                .order_by("order")
                .extra(**tag.extra_query)  # type: ignore
                # If there's two of the same element, for the second one we need to shift one
                [tag.unique_order : tag.unique_order + 1]
            )
            filter["match_{}__isnull".format(index)] = False
            if index > 0:
                # If direct descendant, the next element has to have order +1
                if tag.direct_descendant:
                    filter["match_{}".format(index)] = F("match_{}".format(index - 1)) + 1
                else:
                    # If not, it can have any order as long as it's bigger than current element
                    filter["match_{}__gt".format(index)] = F("match_{}".format(index - 1))
        return (subqueries, filter)

    def earliest_timestamp(self, team_id: int):
        return (
            self.filter(team_id=team_id)
            .order_by("timestamp")[0]
            .timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )

    def filter_by_element(self, filters: Dict, team_id: int):
        groups = ElementGroup.objects.filter(team_id=team_id)

        if filters.get("selector"):
            selector = Selector(filters["selector"])
            subqueries, filter = self._element_subquery(selector)
            groups = groups.annotate(**subqueries)  # type: ignore
        else:
            filter = {}

        for key in ["tag_name", "text", "href"]:
            if filters.get(key):
                filter["element__{}".format(key)] = filters[key]

        if not filter:
            return {}

        groups = groups.filter(**filter)
        return {"elements_hash__in": groups.values_list("hash", flat=True)}

    def filter_by_url(self, action_step: ActionStep, subquery: QuerySet):
        if not action_step.url:
            return subquery
        if action_step.url_matching == ActionStep.EXACT:
            where, param = "properties->>'$current_url' = %s", action_step.url
        elif action_step.url_matching == ActionStep.REGEX:
            where, param = "properties->>'$current_url' ~ %s", action_step.url
        else:
            where, param = "properties->>'$current_url' LIKE %s", f"%{action_step.url}%"
        return subquery.extra(where=[where], params=[param])

    def filter_by_event(self, action_step):
        if not action_step.event:
            return {}
        return {"event": action_step.event}

    def filter_by_period(self, start, end):
        if not start and not end:
            return {}
        if not start:
            return {"created_at__lte": end}
        if not end:
            return {"created_at__gte": start}
        return {"created_at__gte": start, "created_at__lte": end}

    def add_person_id(self, team_id: int):
        return self.annotate(
            person_id=Subquery(
                PersonDistinctId.objects.filter(team_id=team_id, distinct_id=OuterRef("distinct_id"))
                .order_by()
                .values("person_id")[:1]
            )
        )

    def query_db_by_action(self, action, order_by="-timestamp", start=None, end=None) -> models.QuerySet:
        from posthog.queries.base import properties_to_Q

        events = self
        any_step = Q()
        steps = action.steps.all()
        if len(steps) == 0:
            return self.none()

        for step in steps:
            step_filter = Filter(data={"properties": step.properties})

            subquery = (
                Event.objects.add_person_id(team_id=action.team_id)
                .filter(
                    properties_to_Q(step_filter.properties, team_id=action.team_id),
                    pk=OuterRef("id"),
                    **self.filter_by_event(step),
                    **self.filter_by_element(model_to_dict(step), team_id=action.team_id),
                    **self.filter_by_period(start, end),
                )
                .only("id")
            )
            subquery = self.filter_by_url(step, subquery)
            any_step |= Q(Exists(subquery))
        events = self.filter(team_id=action.team_id).filter(any_step)

        if order_by:
            events = events.order_by(order_by)

        return events

    def filter_by_action(self, action: Action, order_by: str = "-id") -> models.QuerySet:
        events = self.filter(action=action).add_person_id(team_id=action.team_id)
        if order_by:
            events = events.order_by(order_by)
        return events

    def filter_by_event_with_people(self, event, team_id: int, order_by: str = "-id") -> models.QuerySet:
        events = self.filter(team_id=team_id).filter(event=event).add_person_id(team_id=team_id)
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

            # Matching actions to events can get very expensive to do as events are streaming in
            # In a few cases we have had it OOM Postgres with the query it is running
            # Short term solution is to have this be configurable to be run in batch
            if not settings.ASYNC_EVENT_ACTION_MAPPING:
                should_post_webhook = False
                relations = []
                for action in event.actions:
                    relations.append(action.events.through(action_id=action.pk, event_id=event.pk))
                    if is_ee_enabled():
                        continue  # avoiding duplication here - in EE hooks are handled by webhooks_ee.py
                    action.on_perform(event)
                    if action.post_to_slack:
                        should_post_webhook = True
                Action.events.through.objects.bulk_create(relations, ignore_conflicts=True)
                team = kwargs.get("team", event.team)
                if (
                    should_post_webhook and team and team.slack_incoming_webhook and not is_ee_enabled()
                ):  # ee will handle separately
                    celery.current_app.send_task("posthog.tasks.webhooks.post_event_to_webhook", (event.pk, site_url))

            return event


class Event(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=["elements_hash"]),
            models.Index(fields=["timestamp", "team_id", "event"]),
        ]

    def _can_use_cached_query(self, last_updated_action_ts):
        if not self.team_id in LAST_UPDATED_TEAM_ACTION:
            return False

        if not self.team_id in TEAM_EVENT_ACTION_QUERY_CACHE:
            return False

        if not self.event in TEAM_EVENT_ACTION_QUERY_CACHE[self.team_id]:
            return False

        if not self.team_id in TEAM_ACTION_QUERY_CACHE:
            return False

        # Cache is expired because actions were updated
        if last_updated_action_ts > LAST_UPDATED_TEAM_ACTION[self.team_id]:
            return False
        return True

    @property
    def person(self):
        return Person.objects.get(
            team_id=self.team_id, persondistinctid__team_id=self.team_id, persondistinctid__distinct_id=self.distinct_id
        )

    # This (ab)uses query_db_by_action to find which actions match this event
    # We can't use filter_by_action here, as we use this function when we create an event so
    # the event won't be in the Action-Event relationship yet.
    # We use query caching to reduce the time spent on generating redundant queries
    @property
    def actions(self) -> List:
        last_updated_action_ts = Action.objects.filter(team_id=self.team_id).aggregate(models.Max("updated_at"))[
            "updated_at__max"
        ]

        actions = (
            Action.objects.filter(
                team_id=self.team_id, steps__event=self.event, deleted=False,  # filter by event name to narrow down
            )
            .distinct("id")
            .prefetch_related(Prefetch("steps", queryset=ActionStep.objects.order_by("id")))
        )
        if not self._can_use_cached_query(last_updated_action_ts):
            TEAM_ACTION_QUERY_CACHE[self.team_id], _ = actions.query.sql_with_params()
            if len(actions) == 0:
                return []
            events: models.QuerySet[Any] = Event.objects.filter(pk=self.pk)
            for action in actions:
                events = events.annotate(
                    **{
                        "action_{}".format(action.pk): Event.objects.filter(pk=self.pk)
                        .query_db_by_action(action)
                        .values("id")[:1]
                    }
                )
            # This block is a little cryptic so bear with me
            # We grab the query and the params from the ORM here
            q, p = events.query.sql_with_params()

            # We then take the parameters and replace the event id's with a placeholder
            # We use this later to sub back in future event id's
            # The rest of the parameters are shared between action types
            qp = tuple(["%s" if i == self.pk else i for i in p])

            # Create a cache item and add it to the cache keyed on team_id and event id
            qcache = {self.event: (q, qp)}
            TEAM_EVENT_ACTION_QUERY_CACHE[self.team_id].update(qcache)

            # Update the last updated team action timestamp for future reference
            LAST_UPDATED_TEAM_ACTION[self.team_id] = last_updated_action_ts
        else:

            # If we have reached this block we are about to use the sql query cache
            # Grab the actions using the cached action query
            actions.raw(TEAM_ACTION_QUERY_CACHE[self.team_id])

            # Grab the cached query and query params, we will need to replace some params
            q, p = TEAM_EVENT_ACTION_QUERY_CACHE[self.team_id][self.event]

            # Replace the query param placeholders with the event id (opposite of what we did above)
            qp = tuple([self.pk if i == "%s" else i for i in p])

            with connection.cursor() as cursor:
                # Format and execute the cached query using the mostly cached params
                qstring = cursor.mogrify(q, qp)
                cursor.execute(qstring)
                events = namedtuplefetchall(cursor)

        event = [event for event in events][0]
        filtered_actions = [action for action in actions if getattr(event, "action_{}".format(action.pk), None)]
        return filtered_actions

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    objects: EventManager = EventManager.as_manager()  # type: ignore
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    event: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    distinct_id: models.CharField = models.CharField(max_length=200)
    properties: JSONField = JSONField(default=dict)
    timestamp: models.DateTimeField = models.DateTimeField(default=timezone.now, blank=True)
    elements_hash: models.CharField = models.CharField(max_length=200, null=True, blank=True)

    # DEPRECATED: elements are stored against element groups now
    elements: JSONField = JSONField(default=list, null=True, blank=True)
