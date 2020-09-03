from typing import Dict

from django.forms.models import model_to_dict

from ee.clickhouse.sql.actions import ELEMENT_ACTION_FILTER, ELEMENT_PROP_FILTER, EVENT_ACTION_FILTER
from posthog.models import Action
from posthog.models.event import Selector


def query_action(action: Action):

    # get action steps
    params = {"team_id": action.team.pk}
    steps = action.steps.all()
    if len(steps) == 0:
        return []

    queries = []
    for step in steps:
        # filter element
        if step.event == "$autocapture":
            element_query = filter_element(model_to_dict(step))
            queries.append(element_query)
        # filter event
        elif step.event:
            event_query = EVENT_ACTION_FILTER.format(property_filter="", event_filter="event = {}".format(step.event))
            queries.append(event_query)


def filter_element(filters: Dict):
    prop_queries = []
    if filters.get("selector"):
        selector = Selector(filters["selector"])
        for index, tag in enumerate(selector.parts):
            prop_queries.append(tag.clickhouse_query(query=ELEMENT_PROP_FILTER))

        for key in ["tag_name", "text", "href"]:
            if filters.get(key):
                prop_queries.append("{} = {}".format(key, filters[key]))

    return ""
