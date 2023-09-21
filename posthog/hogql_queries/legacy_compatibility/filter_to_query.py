from posthog.models.entity.entity import Entity
from posthog.models.filters import AnyInsightFilter
from posthog.models.filters.filter import Filter
from posthog.schema import (
    ActionsNode,
    BreakdownFilter,
    DateRange,
    EventsNode,
    FunnelsQuery,
    LifecycleQuery,
    PathsQuery,
    PropertyGroupFilter,
    RetentionQuery,
    StickinessQuery,
    TrendsFilter,
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


def _breakdown_filter(filter: AnyInsightFilter):
    if filter.insight != "TRENDS" and filter.insight != "FUNNELS":
        return {}

    breakdownFilter = {
        "breakdown_type": filter.breakdown_type,
        "breakdown": filter.breakdown,
        "breakdown_normalize_url": filter.breakdown_normalize_url,
        "breakdown_group_type_index": filter.breakdown_group_type_index,
        "breakdown_histogram_bin_count": filter.breakdown_histogram_bin_count if filter.insight == "TRENDS" else None,
    }

    if filter.breakdowns is not None:
        if len(filter.breakdowns) == 1:
            breakdownFilter["breakdown_type"] = filter.breakdowns[0].get("type", None)
            breakdownFilter["breakdown"] = filter.breakdowns[0].get("property", None)
        else:
            raise Exception("Could not convert multi-breakdown property `breakdowns` - found more than one breakdown")

    if breakdownFilter["breakdown"] is not None and breakdownFilter["breakdown_type"] is None:
        breakdownFilter["breakdown_type"] = "event"

    return {"breakdown": BreakdownFilter(**breakdownFilter)}


def _group_aggregation_filter(filter: AnyInsightFilter):
    return {"aggregation_group_type_index": filter.aggregation_group_type_index}


def _insight_filter(filter: AnyInsightFilter):
    if filter.insight == "TRENDS" and isinstance(filter, Filter):
        return {
            "trendsFilter": TrendsFilter(
                smoothing_intervals=filter.smoothing_intervals,
                # show_legend=filter.show_legend,
                # hidden_legend_indexes=cleanHiddenLegendIndexes(filter.hidden_legend_keys),
                compare=filter.compare,
                aggregation_axis_format=filter.aggregation_axis_format,
                aggregation_axis_prefix=filter.aggregation_axis_prefix,
                aggregation_axis_postfix=filter.aggregation_axis_postfix,
                formula=filter.formula,
                shown_as=filter.shown_as,
                display=filter.display,
                # show_values_on_series=filter.show_values_on_series,
                # show_percent_stack_view=filter.show_percent_stack_view,
            )
        }
    elif filter.insight == "FUNNELS":
        return {}  # TODO: implement
    elif filter.insight == "RETENTION":
        return {}  # TODO: implement
    elif filter.insight == "PATHS":
        return {}  # TODO: implement
    elif filter.insight == "LIFECYCLE":
        return {}  # TODO: implement
    elif filter.insight == "STICKINESS":
        return {}  # TODO: implement
    else:
        raise Exception(f"Invalid insight type {filter.insight}.")


def filter_to_query(filter: AnyInsightFilter) -> InsightQueryNode:
    Query = insight_to_query_type[filter.insight]

    data = {
        **_date_range(filter),
        **_interval(filter),
        **_series(filter),
        **_sampling_factor(filter),
        **_filter_test_accounts(filter),
        **_properties(filter),
        **_breakdown_filter(filter),
        **_group_aggregation_filter(filter),
        **_insight_filter(filter),
    }

    return Query(**data)
