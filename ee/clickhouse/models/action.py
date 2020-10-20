import re
from typing import Dict, List, Optional, Tuple

from django.forms.models import model_to_dict

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.actions import ACTION_QUERY, ELEMENT_ACTION_FILTER, EVENT_ACTION_FILTER, EVENT_NO_PROP_FILTER
from posthog.constants import AUTOCAPTURE_EVENT
from posthog.models import Action, Filter
from posthog.models.action_step import ActionStep
from posthog.models.event import Selector


def query_action(action: Action) -> Optional[List]:
    query, params = format_action_query(action)

    if query:
        return sync_execute(query, params)

    return None


def format_action_filter(action: Action, prepend: str = "", index=0) -> Tuple[str, Dict]:
    # get action steps
    params = {"team_id": action.team.pk}
    steps = action.steps.all()
    if len(steps) == 0:
        return "", {}

    or_queries = []
    for index, step in enumerate(steps):
        # filter element
        if step.event == AUTOCAPTURE_EVENT:
            query, element_params, index = filter_element(step, "{}{}".format(index, prepend), index)
            params = {**params, **element_params}
        # filter event
        else:
            query, event_params, index = filter_event(step, "{}{}".format(index, prepend), index)
            params = {**params, **event_params}

        if step.properties:
            from ee.clickhouse.models.property import parse_prop_clauses

            prop_query, prop_params = parse_prop_clauses(
                "uuid", Filter(data={"properties": step.properties}).properties, action.team
            )
            query += "{}".format(prop_query)
            params = {**params, **prop_params}

        or_queries.append(query)
    or_separator = "OR uuid IN"
    formatted_query = or_separator.join(or_queries)

    return formatted_query, params


def format_action_query(action: Action, prepend: str = "", index=0) -> Tuple[str, Dict]:
    formatted_query, params = format_action_filter(action, prepend, index)

    final_query = ACTION_QUERY.format(action_filter=formatted_query)
    return final_query, params


def filter_event(step, prepend: str = "", index=0) -> Tuple[str, Dict, int]:
    params = {}
    event_filter = ""
    efilter = ""
    property_filter = ""
    if step.url and step.event:
        if step.url_matching == ActionStep.EXACT:
            operation = "trim(BOTH '\"' FROM value) = '{}'".format(step.url)
            params.update({"prop_val_{}".format(index): step.url})
        elif step.url_matching == ActionStep.REGEX:
            operation = "match(trim(BOTH '\"' FROM value), '{}')".format(step.url)
            params.update({"{}_prop_val_{}".format(prepend, index): step.url})
        else:
            operation = "trim(BOTH '\"' FROM value) LIKE %({}_prop_val_{idx})s ".format(prepend, idx=index)
            params.update({"{}_prop_val_{}".format(prepend, index): "%" + step.url + "%"})
        property_filter = "AND key = '$current_url' AND {operation}".format(operation=operation)
        efilter = "AND event = '{}'".format(step.event)

        event_filter = EVENT_ACTION_FILTER.format(event_filter=efilter, property_filter=property_filter)
    elif step.event:
        efilter = "AND event = '{}'".format(step.event)
        event_filter = EVENT_NO_PROP_FILTER.format(event_filter=efilter)

    return event_filter, params, index + 1


def _create_regex(selector: Selector) -> str:
    regex = r""
    for idx, tag in enumerate(selector.parts):
        if tag.data.get("tag_name") and isinstance(tag.data["tag_name"], str):
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


def filter_element(step: ActionStep, prepend: str = "", index=0) -> Tuple[str, Dict, int]:
    event_filter, params, index = filter_event(step, prepend, index) if step.url else ("", {}, index + 1)

    filters = model_to_dict(step)

    if filters.get("selector"):
        selector = Selector(filters["selector"], escape_slashes=False)
        params["{}selector_regex".format(prepend)] = _create_regex(selector)

    if filters.get("tag_name"):
        params["{}tag_name_regex".format(prepend)] = r"(^|;){}(\.|$|;|:)".format(filters["tag_name"])

    attributes: Dict[str, str] = {}
    for key in ["href", "text"]:
        if filters.get(key):
            attributes[key] = re.escape(filters[key])

    attributes_regex = False
    if len(attributes.keys()) > 0:
        attributes_regex = True
        params["{}attributes_regex".format(prepend)] = ".*?({}).*?".format(
            ".*?".join(['{}="{}"'.format(key, value) for key, value in attributes.items()])
        )

    return (
        ELEMENT_ACTION_FILTER.format(
            selector_regex="AND match(elements_chain, %({}selector_regex)s)".format(prepend)
            if filters.get("selector")
            else "",
            attributes_regex="AND match(elements_chain, %({}attributes_regex)s)".format(prepend)
            if attributes_regex
            else "",
            tag_name_regex="AND match(elements_chain, %({}tag_name_regex)s)".format(prepend)
            if filters.get("tag_name")
            else "",
            event_filter="AND uuid IN {}".format(event_filter) if event_filter else "",
        ),
        params,
        index + 1,
    )
