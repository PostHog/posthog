from typing import Dict, List, Optional, Tuple

from django.forms.models import model_to_dict

from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.actions import (
    ACTION_QUERY,
    ELEMENT_ACTION_FILTER,
    ELEMENT_PROP_FILTER,
    EVENT_ACTION_FILTER,
    FILTER_EVENT_BY_ACTION_SQL,
    INSERT_INTO_ACTION_TABLE,
    create_action_mapping_table_sql,
)
from ee.clickhouse.sql.clickhouse import DROP_TABLE_IF_EXISTS_SQL
from posthog.constants import AUTOCAPTURE_EVENT
from posthog.models import Action, Team
from posthog.models.action_step import ActionStep
from posthog.models.event import Selector


def format_action_table_name(action: Action) -> str:
    return "action_" + str(action.team.pk) + "_" + str(action.pk)


def filter_events_by_action(action: Action) -> List:
    query = format_events_by_action_query(action)
    return ch_client.execute(query)


def format_events_by_action_query(action: Action) -> str:
    table_name = format_action_table_name(action)
    return FILTER_EVENT_BY_ACTION_SQL.format(table_name=table_name)


def populate_action_event_table(action: Action) -> None:
    query, params = format_action_query(action)

    table_name = format_action_table_name(action)

    ch_client.execute(DROP_TABLE_IF_EXISTS_SQL.format(table_name))

    ch_client.execute(create_action_mapping_table_sql(table_name))

    final_query = INSERT_INTO_ACTION_TABLE.format(query=query, table_name=table_name)

    ch_client.execute(final_query, params)


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
            element_query, element_params = filter_element(step)
            params = {**params, **element_params}
            or_queries.append(element_query)

        # filter event
        elif step.event:
            event_query, event_params = filter_event(step)
            params = {**params, **event_params}
            or_queries.append(event_query)

    or_separator = "OR id IN"
    formatted_query = or_separator.join(or_queries)

    final_query = ACTION_QUERY.format(action_filter=formatted_query)

    return final_query, params


def filter_event(step) -> Tuple[str, Dict]:
    params = {}
    event_filter = ""
    efilter = ""
    property_filter = ""
    if step.url:
        if step.url_matching == ActionStep.EXACT:
            operation = "value = '{}'".format(step.url)
            params.update({"prop_val": step.url})
        elif step.url_matching == ActionStep.REGEX:
            operation = "like(value, '{}')".format(step.url)
            params.update({"prop_val": step.url})
        else:
            operation = "value LIKE %(prop_val)s ".format(step.url)
            params.update({"prop_val": "%" + step.url + "%"})
        property_filter = "AND key = '$current_url' AND {operation}".format(operation=operation)

    if step.event:
        efilter = "AND event = '{}'".format(step.event)

    event_filter = EVENT_ACTION_FILTER.format(event_filter=efilter, property_filter=property_filter)

    return event_filter, params


def filter_element(step: ActionStep) -> Tuple[str, Dict]:
    event_filter, params = filter_event(step) if step.url else ("", {})

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

    return (
        ELEMENT_ACTION_FILTER.format(element_filter=selector_query, event_filter="AND id IN {}".format(event_filter)),
        params,
    )
