from typing import Dict, List, Optional, Tuple

from django.forms.models import model_to_dict

from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.actions import ACTION_QUERY, ELEMENT_ACTION_FILTER, ELEMENT_PROP_FILTER, EVENT_ACTION_FILTER
from posthog.constants import AUTOCAPTURE_EVENT
from posthog.models import Action
from posthog.models.action_step import ActionStep
from posthog.models.event import Selector


def query_action(action: Action) -> Optional[List]:
    query, params = format_action_query(action)

    if query:
        return ch_client.execute(query, params)

    return None


def format_action_query(action: Action) -> Tuple[str, Dict]:
    # get action steps
    params = {"team_id": action.team.pk}
    steps = action.steps.all()
    if len(steps) == 0:
        return "", {}

    or_queries = []
    for step in steps:
        # filter element
        if step.event == AUTOCAPTURE_EVENT:
            element_query = filter_element(step)
            or_queries.append(element_query)

        # filter event
        elif step.event:
            event_query = filter_event(step)
            or_queries.append(event_query)

    or_separator = "OR id IN"
    formatted_query = or_separator.join(or_queries)

    final_query = ACTION_QUERY.format(action_filter=formatted_query)

    return final_query, params


def handle_url(step) -> str:
    event_filter = ""
    if step.url:
        operator = "LIKE"
        if step.url_matching == ActionStep.EXACT:
            operator = "="
        event_filter = "AND id IN {}".format(
            EVENT_ACTION_FILTER.format(
                event_filter="",
                property_filter="AND key = '$current_url' AND value {operator} '{}'".format(
                    step.url, operator=operator
                ),
            )
        )
    return event_filter


def filter_event(step: ActionStep) -> str:
    event_query = EVENT_ACTION_FILTER.format(property_filter="", event_filter="AND event = '{}'".format(step.event))
    return event_query


def filter_element(step: ActionStep) -> str:
    event_filter = handle_url(step)

    filters = model_to_dict(step)

    prop_queries = []
    if filters.get("selector"):
        selector = Selector(filters["selector"])
        for index, tag in enumerate(selector.parts):
            prop_queries.append(tag.clickhouse_query(query=ELEMENT_PROP_FILTER))

        for key in ["tag_name", "text", "href"]:
            if filters.get(key):
                prop_queries.append("{} = '{}'".format(key, filters[key]))
    separator = " AND "
    selector_query = separator.join(prop_queries)

    return ELEMENT_ACTION_FILTER.format(element_filter=selector_query, event_filter=event_filter)
