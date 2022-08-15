from typing import Counter, Dict, List, Tuple

from django.forms.models import model_to_dict

from posthog.constants import AUTOCAPTURE_EVENT, TREND_FILTER_TYPE_ACTIONS
from posthog.models import Entity, Filter
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.property import Property, PropertyIdentifier
from posthog.models.utils import PersonPropertiesMode


def format_action_filter(
    team_id: int,
    action: Action,
    prepend: str = "action",
    use_loop: bool = False,
    filter_by_team=True,
    table_name: str = "",
    person_properties_mode: PersonPropertiesMode = PersonPropertiesMode.USING_SUBQUERY,
    person_id_joined_alias: str = "person_id",
) -> Tuple[str, Dict]:
    # get action steps
    params = {"team_id": action.team.pk} if filter_by_team else {}
    steps = action.steps.all()
    if len(steps) == 0:
        # If no steps, it shouldn't match this part of the query
        return "1=2", {}

    or_queries = []
    for index, step in enumerate(steps):
        conditions: List[str] = []
        # filter element
        if step.event == AUTOCAPTURE_EVENT:
            from posthog.models.property.util import filter_element  # prevent circular import

            el_condition, element_params = filter_element(model_to_dict(step), prepend=f"{action.pk}_{index}{prepend}")
            params = {**params, **element_params}
            if len(el_condition) > 0:
                conditions.append(el_condition)

        # filter event conditions (ie URL)
        event_conditions, event_params = filter_event(step, f"{action.pk}_{index}{prepend}", index, table_name)
        params = {**params, **event_params}
        conditions += event_conditions

        if step.properties:
            from posthog.models.property.util import parse_prop_grouped_clauses

            prop_query, prop_params = parse_prop_grouped_clauses(
                team_id=team_id,
                property_group=Filter(data={"properties": step.properties}).property_groups,
                prepend=f"action_props_{action.pk}_{step.pk}",
                table_name=table_name,
                person_properties_mode=person_properties_mode,
                person_id_joined_alias=person_id_joined_alias,
            )
            conditions.append(prop_query.replace("AND", "", 1))
            params = {**params, **prop_params}

        if len(conditions) > 0:
            or_queries.append(" AND ".join(conditions))
    if use_loop:
        formatted_query = "SELECT uuid FROM events WHERE {} AND team_id = %(team_id)s".format(
            ") OR uuid IN (SELECT uuid FROM events WHERE team_id = %(team_id)s AND ".join(or_queries)
        )
    else:
        formatted_query = "(({}))".format(") OR (".join(or_queries))
    return formatted_query, params


def filter_event(
    step: ActionStep, prepend: str = "event", index: int = 0, table_name: str = ""
) -> Tuple[List[str], Dict]:
    from posthog.models.property.util import get_property_string_expr

    params = {"{}_{}".format(prepend, index): step.event}
    conditions = []

    if table_name != "":
        table_name += "."

    if step.url:
        value_expr, _ = get_property_string_expr("events", "$current_url", "'$current_url'", f"{table_name}properties")
        prop_name = f"{prepend}_prop_val_{index}"
        if step.url_matching == ActionStep.EXACT:
            conditions.append(f"{value_expr} = %({prop_name})s")
            params.update({prop_name: step.url})
        elif step.url_matching == ActionStep.REGEX:
            conditions.append(f"match({value_expr}, %({prop_name})s)")
            params.update({prop_name: step.url})
        else:
            conditions.append(f"{value_expr} LIKE %({prop_name})s")
            params.update({prop_name: f"%{step.url}%"})

    conditions.append(f"event = %({prepend}_{index})s")

    return conditions, params


def format_entity_filter(
    team_id: int, entity: Entity, person_id_joined_alias: str, prepend: str = "action", filter_by_team=True
) -> Tuple[str, Dict]:
    if entity.type == TREND_FILTER_TYPE_ACTIONS:
        action = entity.get_action()
        entity_filter, params = format_action_filter(
            team_id=team_id,
            action=action,
            prepend=prepend,
            filter_by_team=filter_by_team,
            person_id_joined_alias=person_id_joined_alias,
        )
    else:
        key = f"{prepend}_event"
        entity_filter = f"event = %({key})s"
        params = {key: entity.id}

    return entity_filter, params


def get_action_tables_and_properties(action: Action) -> Counter[PropertyIdentifier]:
    from posthog.models.property.util import extract_tables_and_properties

    result: Counter[PropertyIdentifier] = Counter()

    for action_step in action.steps.all():
        if action_step.url:
            result[("$current_url", "event", None)] += 1
        result += extract_tables_and_properties(
            Filter(data={"properties": action_step.properties or []}).property_groups.flat
        )

    return result


def uses_elements_chain(action: Action) -> bool:
    for action_step in action.steps.all():
        if any(Property(**prop).type == "element" for prop in (action_step.properties or [])):
            return True
        if any(getattr(action_step, attribute) is not None for attribute in ["selector", "tag_name", "href", "text"]):
            return True
    return False
