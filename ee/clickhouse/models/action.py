import re
from typing import Dict, List, Tuple

from django.forms.models import model_to_dict

from posthog.constants import AUTOCAPTURE_EVENT, TREND_FILTER_TYPE_ACTIONS
from posthog.models import Action, Entity, Filter
from posthog.models.action_step import ActionStep
from posthog.models.event import Selector


def format_action_filter(action: Action, prepend: str = "action", use_loop: bool = False) -> Tuple[str, Dict]:
    # get action steps
    params = {"team_id": action.team.pk}
    steps = action.steps.all()
    if len(steps) == 0:
        # If no steps, it shouldn't match this part of the query
        return "1=2", {}

    or_queries = []
    for index, step in enumerate(steps):
        conditions: List[str] = []
        # filter element
        if step.event == AUTOCAPTURE_EVENT:
            el_conditions, element_params = filter_element(step, "{}_{}{}".format(action.pk, index, prepend))
            params = {**params, **element_params}
            conditions += el_conditions

        # filter event conditions (ie URL)
        event_conditions, event_params = filter_event(step, "{}_{}{}".format(action.pk, index, prepend), index)
        params = {**params, **event_params}
        conditions += event_conditions

        if step.properties:
            from ee.clickhouse.models.property import parse_prop_clauses

            prop_query, prop_params = parse_prop_clauses(
                Filter(data={"properties": step.properties}).properties,
                action.team.pk,
                prepend="action_props_{}".format(action.pk),
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


def filter_event(step: ActionStep, prepend: str = "event", index: int = 0) -> Tuple[List[str], Dict]:
    params = {"{}_{}".format(prepend, index): step.event}
    conditions = []

    if step.url:
        if step.url_matching == ActionStep.EXACT:
            conditions.append(
                "JSONExtractString(properties, '$current_url') = %({}_prop_val_{})s".format(prepend, index)
            )
            params.update({"{}_prop_val_{}".format(prepend, index): step.url})
        elif step.url_matching == ActionStep.REGEX:
            conditions.append(
                "match(JSONExtractString(properties, '$current_url'), %({}_prop_val_{})s)".format(prepend, index)
            )
            params.update({"{}_prop_val_{}".format(prepend, index): step.url})
        else:
            conditions.append(
                "JSONExtractString(properties, '$current_url') LIKE %({}_prop_val_{})s".format(prepend, index)
            )
            params.update({"{}_prop_val_{}".format(prepend, index): "%" + step.url + "%"})

    conditions.append("event = %({}_{})s".format(prepend, index))

    return conditions, params


def _create_regex(selector: Selector) -> str:
    regex = r""
    for idx, tag in enumerate(selector.parts):
        if tag.data.get("tag_name") and isinstance(tag.data["tag_name"], str):
            if tag.data["tag_name"] == "*":
                regex += ".+"
            else:
                regex += tag.data["tag_name"]
        if tag.data.get("attr_class__contains"):
            regex += r".*?\.{}".format(r"\..*?".join(sorted(tag.data["attr_class__contains"])))
        if tag.ch_attributes:
            regex += ".*?"
            for key, value in sorted(tag.ch_attributes.items()):
                regex += '{}="{}".*?'.format(key, value)
        regex += r"([-_a-zA-Z0-9\.]*?)?($|;|:([^;^\s]*(;|$|\s)))"
        if tag.direct_descendant:
            regex += ".*"
    return regex


def filter_element(step: ActionStep, prepend: str = "") -> Tuple[List[str], Dict]:
    filters = model_to_dict(step)
    params = {}
    conditions = []

    if filters.get("selector"):
        selector = Selector(filters["selector"], escape_slashes=False)
        params["{}selector_regex".format(prepend)] = _create_regex(selector)
        conditions.append("match(elements_chain, %({}selector_regex)s)".format(prepend))

    if filters.get("tag_name"):
        params["{}tag_name_regex".format(prepend)] = r"(^|;){}(\.|$|;|:)".format(filters["tag_name"])
        conditions.append("match(elements_chain, %({}tag_name_regex)s)".format(prepend))

    attributes: Dict[str, str] = {}
    for key in ["href", "text"]:
        if filters.get(key):
            attributes[key] = re.escape(filters[key])

    if len(attributes.keys()) > 0:
        params["{}attributes_regex".format(prepend)] = ".*?({}).*?".format(
            ".*?".join(['{}="{}"'.format(key, value) for key, value in attributes.items()])
        )
        conditions.append("match(elements_chain, %({}attributes_regex)s)".format(prepend))

    return (conditions, params)


def format_entity_filter(entity: Entity, prepend: str = "action") -> Tuple[str, Dict]:
    if entity.type == TREND_FILTER_TYPE_ACTIONS:
        try:
            action = Action.objects.get(pk=entity.id)
            entity_filter, params = format_action_filter(action, prepend=prepend)
        except Action.DoesNotExist:
            raise ValueError("This action does not exist")
    else:
        key = f"{prepend}_event"
        entity_filter = f"event = %({key})s"
        params = {key: entity.id}

    return entity_filter, params
