from typing import Dict, Any, List, Union
from posthog.models.entity.entity import Entity

from posthog.schema import ActionsNode, EventsNode, TrendsQuery


def query_node_to_filter(query: TrendsQuery) -> Dict[str, Any]:
    filter = {
        # 'properties': query['properties'],
        # 'filter_test_accounts': query['filterTestAccounts'],
        # 'date_to': query['dateRange']['date_to'] if 'dateRange' in query else None,
        # 'date_from': query['dateRange']['date_from'] if 'dateRange' in query else None,
        # 'entity_type': 'events',
        # 'sampling_factor': query['samplingFactor']
        "interval": query.interval,
        "kind": query.kind,
        "date_from": query.dateRange.date_from,
        # query.series
        "events": series_to_actions_and_events(query.series)
        # series
    }

    return filter


def series_to_actions_and_events(series: List[Union[EventsNode, ActionsNode]]) -> List[Entity]:
    # actions = []
    events = []
    for index, node in enumerate(series):
        entity = {
            # "type": EntityTypes.EVENTS if isEventsNode(node)
            #         else EntityTypes.ACTIONS if isActionsNode(node)
            "type": "event",
            # "id": (node.event if not isActionsNode(node) else node.id) or None,
            "id": node.event,
            "order": index,
            "name": node.name,
            "custom_name": node.custom_name,
            "math": node.math,
            "math_property": node.math_property,
            "math_group_type_index": node.math_group_type_index,
            "properties": node.properties,
        }

    # if isEventsNode(node):
    #     events.append(entity)
    # elif isActionsNode(node):
    #     actions.append(entity)
    # else:
    #     new_entity.append(entity)
    events.append(entity)

    # return {actions, events, new_entity}
    return events
