import re
from typing import NamedTuple

import structlog
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    CohortPropertyFilter,
    EventPropertyFilter,
    EventsNode,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    PersonPropertyFilter,
    PersonsOnEventsMode,
    PropertyOperator,
    QueryTiming,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, property_to_expr

from posthog.models import Action, Team
from posthog.types import AnyPropertyFilter

logger = structlog.get_logger(__name__)

NEGATIVE_OPERATORS = [
    PropertyOperator.IS_NOT_SET,
    PropertyOperator.IS_NOT,
    PropertyOperator.NOT_REGEX,
    PropertyOperator.NOT_ICONTAINS,
    # PropertyOperator.NOT_BETWEEN, # in the schema but not used anywhere
    # PropertyOperator.NOT_IN,  # COHORT operator we don't need to handle it explicitly
]

INVERSE_OPERATOR_FOR = {
    PropertyOperator.IS_NOT_SET: PropertyOperator.IS_SET,
    PropertyOperator.IS_NOT: PropertyOperator.EXACT,
    PropertyOperator.NOT_IN: PropertyOperator.IN_,
    PropertyOperator.NOT_REGEX: PropertyOperator.REGEX,
    PropertyOperator.NOT_ICONTAINS: PropertyOperator.ICONTAINS,
    PropertyOperator.NOT_BETWEEN: PropertyOperator.BETWEEN,
}


def is_event_property(p: AnyPropertyFilter) -> bool:
    p_type = getattr(p, "type", None)
    p_key = getattr(p, "key", "")
    return p_type == "event" or (p_type == "hogql" and bool(re.search(r"(?<!person\.)properties\.", p_key)))


def is_person_property(p: AnyPropertyFilter) -> bool:
    p_type = getattr(p, "type", None)
    p_key = getattr(p, "key", "")
    return p_type == "person" or (p_type == "hogql" and "person.properties" in p_key)


def is_group_property(p: AnyPropertyFilter) -> bool:
    p_type = getattr(p, "type", None)
    return p_type == "group"


def is_cohort_property(p: AnyPropertyFilter) -> bool:
    p_type = getattr(p, "type", None)
    return bool(p_type and "cohort" in p_type)


def expand_test_account_filters(team: Team) -> list[AnyPropertyFilter]:
    prop_filters: list[AnyPropertyFilter] = []
    for prop in team.test_account_filters:
        match prop.get("type", None):
            case "person":
                prop_filters.append(PersonPropertyFilter(**prop))
            case "event":
                prop_filters.append(EventPropertyFilter(**prop))
            case "group":
                prop_filters.append(GroupPropertyFilter(**prop))
            case "hogql":
                prop_filters.append(HogQLPropertyFilter(**prop))
            case "cohort":
                prop_filters.append(CohortPropertyFilter(**prop))
            case None:
                logger.warn("test account filter had no type", filter=prop)
                prop_filters.append(EventPropertyFilter(**prop))

    return prop_filters


class SessionRecordingQueryResult(NamedTuple):
    results: list
    has_more_recording: bool
    timings: list[QueryTiming] | None = None
    next_cursor: str | None = None


class UnexpectedQueryProperties(Exception):
    def __init__(self, remaining_properties: list[AnyPropertyFilter] | None):
        self.remaining_properties = remaining_properties
        super().__init__(f"Unexpected properties in query: {remaining_properties}")


def _strip_person_and_event_and_cohort_properties(
    properties: list[AnyPropertyFilter] | None,
) -> list[AnyPropertyFilter] | None:
    if not properties:
        return None

    properties_to_keep = [
        p
        for p in properties
        if not is_event_property(p)
        and not is_person_property(p)
        and not is_group_property(p)
        and not is_cohort_property(p)
    ]

    return properties_to_keep


def poe_is_active(team: Team) -> bool:
    return team.person_on_events_mode is not None and team.person_on_events_mode != PersonsOnEventsMode.DISABLED


def _entity_to_expr(entity: EventsNode | ActionsNode, team: Team) -> ast.Expr:
    # KLUDGE: we should be able to use NodeKind.ActionsNode here but mypy :shrug:
    if entity.kind == "ActionsNode":
        # action
        try:
            action = Action.objects.get(pk=entity.id)
        except Action.DoesNotExist:
            raise ValidationError(f"Action ID {entity.id} does not exist!")

        event_expr = action_to_expr(action)
    elif entity.event is None:
        # all events
        event_expr = ast.Constant(value=True)
    else:
        # event
        event_expr = parse_expr("events.event = {event}", {"event": ast.Constant(value=entity.name)})

    if entity.fixedProperties is not None and entity.fixedProperties != []:
        # add property filters
        filter_expr = property_to_expr(entity.fixedProperties, team)
        return ast.And(exprs=[event_expr, filter_expr])
    else:
        return event_expr
