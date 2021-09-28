import copy
import datetime
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple, Union

from dateutil.relativedelta import relativedelta
from django.db import connection, models, transaction
from django.db.models import Exists, F, OuterRef, Prefetch, Q, QuerySet, Subquery
from django.forms.models import model_to_dict
from django.utils import timezone

from .action import Action
from .action_step import ActionStep
from .element import Element
from .element_group import ElementGroup
from .filters import Filter
from .person import Person, PersonDistinctId
from .team import Team
from .utils import namedtuplefetchall

SELECTOR_ATTRIBUTE_REGEX = r"([a-zA-Z]*)\[(.*)=[\'|\"](.*)[\'|\"]\]"


LAST_UPDATED_TEAM_ACTION: Dict[int, datetime.datetime] = {}
TEAM_EVENT_ACTION_QUERY_CACHE: Dict[int, Dict[str, tuple]] = defaultdict(dict)
# TEAM_EVENT_ACTION_QUERY_CACHE looks like team_id -> event ex('$pageview') -> query
TEAM_ACTION_QUERY_CACHE: Dict[int, str] = {}
DEFAULT_EARLIEST_TIME_DELTA = relativedelta(weeks=1)


class SelectorPart(object):
    direct_descendant = False
    unique_order = 0

    def __init__(self, tag: str, direct_descendant: bool, escape_slashes: bool):
        self.direct_descendant = direct_descendant
        self.data: Dict[str, Union[str, List]] = {}
        self.ch_attributes: Dict[str, Union[str, List]] = {}  # attributes for CH

        result = re.search(SELECTOR_ATTRIBUTE_REGEX, tag)
        if result and "[id=" in tag:
            self.data["attr_id"] = result[3]
            self.ch_attributes["attr_id"] = result[3]
            tag = result[1]
        if result and "[" in tag:
            self.data[f"attributes__attr__{result[2]}"] = result[3]
            self.ch_attributes[result[2]] = result[3]
            tag = result[1]
        if "nth-child(" in tag:
            parts = tag.split(":nth-child(")
            self.data["nth_child"] = parts[1].replace(")", "")
            self.ch_attributes["nth-child"] = self.data["nth_child"]
            tag = parts[0]
        if "." in tag:
            parts = tag.split(".")
            # Strip all slashes that are not followed by another slash
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
                where.append(f"(attributes ->> 'attr__{key.split('attr__')[1]}') = %s")
            else:
                if "__contains" in key:
                    where.append(f"{key.replace('__contains', '')} @> %s::varchar(200)[]")
                else:
                    where.append(f"{key} = %s")
            params.append(value)
        return {"where": where, "params": params}

    def _unescape_class(self, class_name):
        r"""Separate all double slashes "\\" (replace them with "\") and remove all single slashes between them."""
        return "\\".join([p.replace("\\", "") for p in class_name.split("\\\\")])


class Selector(object):
    parts: List[SelectorPart] = []

    def __init__(self, selector: str, escape_slashes=True):
        self.parts = []
        # Sometimes people manually add *, just remove them as they don't do anything
        selector = selector.replace("> * > ", "").replace("> *", "").strip()
        tags = list(self._split(selector))
        tags.reverse()
        # Detecting selector parts
        for index, tag in enumerate(tags):
            if tag == ">" or tag == "":
                continue
            direct_descendant = index > 0 and tags[index - 1] == ">"
            part = SelectorPart(tag, direct_descendant, escape_slashes)
            part.unique_order = len([p for p in self.parts if p.data == part.data])
            self.parts.append(copy.deepcopy(part))

    def _split(self, selector):
        in_attribute_selector = False
        in_quotes: Optional[str] = None
        part: List[str] = []
        for char in selector:
            if char == "[" and in_quotes is None:
                in_attribute_selector = True
            if char == "]" and in_quotes is None:
                in_attribute_selector = False
            if char in "\"'":
                if in_quotes is not None:
                    if in_quotes == char:
                        in_quotes = None
                else:
                    in_quotes = char

            if char == " " and not in_attribute_selector:
                yield "".join(part)
                part = []
            else:
                part.append(char)

        yield "".join(part)


class EventManager(models.QuerySet):
    def _element_subquery(self, selector: Selector) -> Tuple[Dict[str, Subquery], Dict[str, Union[F, bool]]]:
        filter: Dict[str, Union[F, bool]] = {}
        subqueries = {}
        for index, tag in enumerate(selector.parts):
            subqueries[f"match_{index}"] = Subquery(
                Element.objects.filter(group_id=OuterRef("pk"))
                .values("order")
                .order_by("order")
                .extra(**tag.extra_query)  # type: ignore
                # If there's two of the same element, for the second one we need to shift one
                [tag.unique_order : tag.unique_order + 1]
            )
            filter[f"match_{index}__isnull"] = False
            if index > 0:
                # If direct descendant, the next element has to have order +1
                if tag.direct_descendant:
                    filter[f"match_{index}"] = F(f"match_{index - 1}") + 1
                else:
                    # If not, it can have any order as long as it's bigger than current element
                    filter[f"match_{index}__gt"] = F(f"match_{index - 1}")
        return (subqueries, filter)

    def earliest_timestamp(self, team_id: int):
        timestamp = self.filter(team_id=team_id).order_by("timestamp").values_list("timestamp", flat=True).first()
        if timestamp is None:
            timestamp = timezone.now() - DEFAULT_EARLIEST_TIME_DELTA

        return timestamp.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    def filter_by_element(self, filters: Dict, team_id: int):
        groups = ElementGroup.objects.filter(team_id=team_id)

        filter = Q()
        if filters.get("selector"):
            selector = Selector(filters["selector"])
            subqueries, subq_filter = self._element_subquery(selector)
            filter = Q(**subq_filter)
            groups = groups.annotate(**subqueries)  # type: ignore
        else:
            filter = Q()

        for key in ["tag_name", "text", "href"]:
            values = filters.get(key, [])

            if not values:
                continue

            values = values if isinstance(values, list) else [values]
            if len(values) == 0:
                continue

            condition = Q()
            for searched_value in values:
                condition |= Q(**{f"element__{key}": searched_value})
            filter &= condition

        if not filter:
            return {}

        groups = groups.filter(filter)

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

    def create(self, *args: Any, **kwargs: Any):
        site_url = kwargs.get("site_url")

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
            return super().create(*args, **kwargs)


class Event(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=["elements_hash"]),
            models.Index(fields=["timestamp", "team_id", "event"]),
            # Separately managed:
            # models.Index(fields=["created_at"]),
            # NOTE: The below index has been added as a manual migration in
            # `posthog/migrations/0024_add_event_distinct_id_index.py, but I'm
            # adding this here to improve visibility.
            # models.Index(fields=["distinct_id"], name="idx_distinct_id"),
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
                        f"action_{action.pk}": Event.objects.filter(pk=self.pk)
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
        filtered_actions = [action for action in actions if getattr(event, f"action_{action.pk}", None)]
        return filtered_actions

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    event: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    distinct_id: models.CharField = models.CharField(max_length=200)
    properties: models.JSONField = models.JSONField(default=dict)
    timestamp: models.DateTimeField = models.DateTimeField(default=timezone.now, blank=True)
    elements_hash: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    site_url: models.CharField = models.CharField(max_length=200, null=True, blank=True)

    # DEPRECATED: elements are stored against element groups now
    elements: models.JSONField = models.JSONField(default=list, null=True, blank=True)

    objects: EventManager = EventManager.as_manager()  # type: ignore
