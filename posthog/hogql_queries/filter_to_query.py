from posthog.models.entity.entity import Entity
from posthog.models.filters import AnyInsightFilter
from posthog.schema import (
    ActionsNode,
    DateRange,
    EventsNode,
    FunnelsQuery,
    LifecycleQuery,
    PathsQuery,
    PropertyGroupFilter,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
)
from posthog.types import InsightQueryNode


def entity_to_node(entity: Entity) -> EventsNode | ActionsNode:
    shared = {
        "name": entity.name,
        "custom_name": entity.custom_name,
        "properties": entity._data.get("properties", None),
        "math": entity.math,
        "math_property": entity.math_property,
        "math_hogql": entity.math_hogql,
        "math_group_type_index": entity.math_group_type_index,
    }

    if entity.type == "actions":
        return ActionsNode(id=entity.id, **shared)
    else:
        return EventsNode(event=entity.id, **shared)


insight_to_query_type = {
    "TRENDS": TrendsQuery,
    "FUNNELS": FunnelsQuery,
    "RETENTION": RetentionQuery,
    "PATHS": PathsQuery,
    "LIFECYCLE": LifecycleQuery,
    "STICKINESS": StickinessQuery,
}


def _date_range(filter: AnyInsightFilter):
    return {"dateRange": DateRange(**filter.date_to_dict())}


def _interval(filter: AnyInsightFilter):
    if filter.insight == "RETENTION" or filter.insight == "PATHS":
        return {}
    return {"interval": filter.interval}


def _series(filter: AnyInsightFilter):
    if filter.insight == "RETENTION" or filter.insight == "PATHS":
        return {}
    return {"series": map(entity_to_node, filter.entities)}


def _sampling_factor(filter: AnyInsightFilter):
    return {"samplingFactor": filter.sampling_factor}


def _filter_test_accounts(filter: AnyInsightFilter):
    return {"filterTestAccounts": filter.filter_test_accounts}


def _properties(filter: AnyInsightFilter):
    raw_properties = filter._data.get("properties", None)
    if raw_properties is None or len(raw_properties) == 0:
        return {}
    elif isinstance(raw_properties, list):
        raw_properties = {"type": "AND", "values": [{"type": "AND", "values": raw_properties}]}
        return {"properties": PropertyGroupFilter(**raw_properties)}
    else:
        return {"properties": PropertyGroupFilter(**raw_properties)}


def filter_to_query(filter: AnyInsightFilter) -> InsightQueryNode:
    Query = insight_to_query_type[filter.insight]

    data = {
        **_date_range(filter),
        **_interval(filter),
        **_series(filter),
        **_sampling_factor(filter),
        **_filter_test_accounts(filter),
        **_properties(filter),
    }

    return Query(**data)
