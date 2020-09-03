from typing import Dict, List, Optional, Tuple

from django.forms.models import model_to_dict

from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.actions import ACTION_QUERY, ELEMENT_ACTION_FILTER, ELEMENT_PROP_FILTER, EVENT_ACTION_FILTER
from posthog.models import Action
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
        if step.event == "$autocapture":
            element_query = filter_element(model_to_dict(step))
            event_filter = ""
            if step.url:
                event_filter = "AND id IN {}".format(
                    EVENT_ACTION_FILTER.format(
                        event_filter="", property_filter="AND key = '$current_url' AND value = '{}'".format(step.url)
                    )
                )
            or_queries.append(ELEMENT_ACTION_FILTER.format(element_filter=element_query, event_filter=event_filter))
        # filter event
        elif step.event:
            event_query = EVENT_ACTION_FILTER.format(
                property_filter="", event_filter="AND event = '{}'".format(step.event)
            )
            or_queries.append(event_query)

    or_separator = "OR id IN"
    formatted_query = or_separator.join(or_queries)

    final_query = ACTION_QUERY.format(action_filter=formatted_query)
    return final_query, params


def filter_element(filters: Dict):
    prop_queries = []
    if filters.get("selector"):
        selector = Selector(filters["selector"])
        for index, tag in enumerate(selector.parts):
            prop_queries.append(tag.clickhouse_query(query=ELEMENT_PROP_FILTER))

        for key in ["tag_name", "text", "href"]:
            if filters.get(key):
                prop_queries.append("{} = '{}'".format(key, filters[key]))
    separator = " AND "

    return separator.join(prop_queries)
