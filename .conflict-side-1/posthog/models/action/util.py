from collections import (
    Counter,
    Counter as TCounter,
)
from typing import Literal, Optional

from posthog.hogql.hogql import HogQLContext

from posthog.constants import AUTOCAPTURE_EVENT
from posthog.models import Filter
from posthog.models.action import Action
from posthog.models.action.action import ActionStepJSON
from posthog.models.property import Property, PropertyIdentifier
from posthog.models.property.property import OperatorType
from posthog.queries.util import PersonPropertiesMode


def format_action_filter_event_only(
    action: Action,
    prepend: str = "action",
) -> tuple[str, dict]:
    """Return SQL for prefiltering events by action, i.e. down to only the events and without any other filters."""
    events = action.get_step_events()
    if not events:
        # If no steps, it shouldn't match this part of the query
        return "1=2", {}
    if None in events:
        # If selecting for "All events", disable entity pre-filtering
        return "1 = 1", {}
    entity_name = f"{prepend}_{action.pk}"
    return f"event IN %({entity_name})s", {entity_name: sorted([x for x in events if x])}


def format_action_filter(
    team_id: int,
    action: Action,
    hogql_context: HogQLContext,
    prepend: str = "action",
    filter_by_team=True,
    table_name: str = "",
    person_properties_mode: PersonPropertiesMode = PersonPropertiesMode.USING_SUBQUERY,
    person_id_joined_alias: str = "person_id",
) -> tuple[str, dict]:
    """Return SQL for filtering events by action."""
    # get action steps
    params = {"team_id": action.team.pk} if filter_by_team else {}
    steps = action.steps
    if len(steps) == 0:
        # If no steps, it shouldn't match this part of the query
        return "1=2", {}

    or_queries = []
    for index, step in enumerate(steps):
        conditions: list[str] = []
        # filter element
        if step.event == AUTOCAPTURE_EVENT:
            from posthog.models.property.util import filter_element  # prevent circular import

            if step.selector:
                element_condition, element_params = filter_element(
                    "selector", step.selector, prepend=f"{action.pk}_{index}{prepend}"
                )
                if element_condition:
                    conditions.append(element_condition)
                    params.update(element_params)
            if step.tag_name:
                element_condition, element_params = filter_element(
                    "tag_name", step.tag_name, prepend=f"{action.pk}_{index}{prepend}"
                )
                if element_condition:
                    conditions.append(element_condition)
                    params.update(element_params)
            if step.href:
                element_condition, element_params = filter_element(
                    "href",
                    step.href,
                    operator=string_matching_to_operator(step.href_matching, "exact"),
                    prepend=f"{action.pk}_{index}{prepend}",
                )
                if element_condition:
                    conditions.append(element_condition)
                    params.update(element_params)
            if step.text:
                element_condition, element_params = filter_element(
                    "text",
                    step.text,
                    operator=string_matching_to_operator(step.text_matching, "exact"),
                    prepend=f"{action.pk}_{index}{prepend}",
                )
                if element_condition:
                    conditions.append(element_condition)
                    params.update(element_params)

        # filter event conditions (ie URL)
        event_conditions, event_params = filter_event(step, f"{action.pk}_{index}{prepend}", index, table_name)
        params.update(event_params)
        conditions += event_conditions

        if step.properties:
            from posthog.models.property.util import parse_prop_grouped_clauses

            prop_query, prop_params = parse_prop_grouped_clauses(
                team_id=team_id,
                property_group=Filter(data={"properties": step.properties}).property_groups,
                prepend=f"action_props_{action.pk}_{index}",
                table_name=table_name,
                person_properties_mode=person_properties_mode,
                person_id_joined_alias=person_id_joined_alias,
                hogql_context=hogql_context,
            )
            conditions.append(prop_query.replace("AND", "", 1))
            params.update(prop_params)

        if len(conditions) > 0:
            or_queries.append(" AND ".join(conditions))
    formatted_query = "(({}))".format(") OR (".join(or_queries))
    return formatted_query, params


def filter_event(
    step: ActionStepJSON, prepend: str = "event", index: int = 0, table_name: str = ""
) -> tuple[list[str], dict]:
    from posthog.models.property.util import get_property_string_expr

    params = {}
    conditions = []

    if table_name != "":
        table_name += "."

    if step.url:
        value_expr, _ = get_property_string_expr("events", "$current_url", "'$current_url'", f"{table_name}properties")
        prop_name = f"{prepend}_prop_val_{index}"
        if step.url_matching == "exact":
            conditions.append(f"{value_expr} = %({prop_name})s")
            params.update({prop_name: step.url})
        elif step.url_matching == "regex":
            conditions.append(f"match({value_expr}, %({prop_name})s)")
            params.update({prop_name: step.url})
        else:
            conditions.append(f"{value_expr} LIKE %({prop_name})s")
            params.update({prop_name: f"%{step.url}%"})

    if step.event:
        params.update({f"{prepend}_{index}": step.event})
        conditions.append(f"event = %({prepend}_{index})s")
    else:
        conditions.append("44 = 44")  # Allow "All events"

    return conditions, params


def get_action_tables_and_properties(action: Action) -> TCounter[PropertyIdentifier]:
    from posthog.models.property.util import extract_tables_and_properties

    result: TCounter[PropertyIdentifier] = Counter()

    for action_step in action.steps:
        if action_step.url:
            result[("$current_url", "event", None)] += 1
        result += extract_tables_and_properties(
            Filter(data={"properties": action_step.properties or []}).property_groups.flat
        )

    return result


def uses_elements_chain(action: Action) -> bool:
    for action_step in action.steps:
        if any(Property(**prop).type == "element" for prop in (action_step.properties or [])):
            return True
        if any(getattr(action_step, attribute) is not None for attribute in ["selector", "tag_name", "href", "text"]):
            return True
    return False


def string_matching_to_operator(
    matching: Optional[Literal["exact", "contains", "regex"]], default: OperatorType
) -> OperatorType:
    if matching == "contains":
        return "icontains"
    return matching or default
