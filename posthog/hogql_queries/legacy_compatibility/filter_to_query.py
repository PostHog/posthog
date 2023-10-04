from typing import List, Dict
from posthog.models.entity.entity import Entity as BackendEntity
from posthog.models.filters import AnyInsightFilter
from posthog.models.filters.filter import Filter as LegacyFilter
from posthog.models.filters.path_filter import PathFilter as LegacyPathFilter
from posthog.models.filters.retention_filter import RetentionFilter as LegacyRetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter as LegacyStickinessFilter
from posthog.schema import (
    ActionsNode,
    BreakdownFilter,
    ChartDisplayType,
    DateRange,
    EventsNode,
    FunnelExclusion,
    FunnelsFilter,
    FunnelsQuery,
    LifecycleFilter,
    LifecycleQuery,
    PathsFilter,
    PathsQuery,
    PropertyGroupFilter,
    RetentionFilter,
    RetentionQuery,
    StickinessFilter,
    StickinessQuery,
    TrendsFilter,
    TrendsQuery,
)
from posthog.types import InsightQueryNode


def is_property_with_operator(property: Dict):
    return property.get("type") not in ("cohort", "hogql")


def clean_property(property: Dict):
    cleaned_property = {**property}

    # fix type typo
    if cleaned_property.get("type") == "events":
        cleaned_property["type"] = "event"

    # convert precalculated cohorts to cohorts
    if cleaned_property.get("type") == "precalculated-cohort":
        cleaned_property["type"] = "cohort"

    # fix invalid property key for cohorts
    if cleaned_property.get("type") == "cohort" and cleaned_property.get("key") != "id":
        cleaned_property["key"] = "id"

    # set a default operator for properties that support it, but don't have an operator set
    if is_property_with_operator(cleaned_property) and cleaned_property.get("operator") is None:
        cleaned_property["operator"] = "exact"

    # remove the operator for properties that don't support it, but have it set
    if not is_property_with_operator(cleaned_property) and cleaned_property.get("operator") is not None:
        del cleaned_property["operator"]

    # remove none from values
    if isinstance(cleaned_property.get("value"), List):
        cleaned_property["value"] = list(filter(lambda x: x is not None, cleaned_property.get("value")))

    # remove keys without concrete value
    cleaned_property = {key: value for key, value in cleaned_property.items() if value is not None}

    return cleaned_property


def clean_entity_properties(properties: List[Dict] | None):
    if properties is None:
        return None
    else:
        return list(map(clean_property, properties))


def clean_property_group_filter_value(value: Dict):
    if value.get("type") in ("AND", "OR"):
        value["values"] = map(clean_property_group_filter_value, value.get("values"))
        return value
    else:
        return clean_property(value)


def clean_properties(properties: Dict):
    properties["values"] = map(clean_property_group_filter_value, properties.get("values"))
    return properties


def clean_display(display: str):
    if display not in ChartDisplayType.__members__:
        return None
    else:
        return display


def entity_to_node(entity: BackendEntity, include_properties: bool, include_math: bool) -> EventsNode | ActionsNode:
    shared = {
        "name": entity.name,
        "custom_name": entity.custom_name,
    }

    if include_properties:
        shared = {
            **shared,
            "properties": clean_entity_properties(entity._data.get("properties", None)),
        }

    if include_math:
        shared = {
            **shared,
            "math": entity.math,
            "math_property": entity.math_property,
            "math_hogql": entity.math_hogql,
            "math_group_type_index": entity.math_group_type_index,
        }

    if entity.type == "actions":
        return ActionsNode(id=entity.id, **shared)
    else:
        return EventsNode(event=entity.id, **shared)


def to_base_entity_dict(entity: BackendEntity):
    return {
        "type": entity.type,
        "id": entity.id,
        "name": entity.name,
        "custom_name": entity.custom_name,
        "order": entity.order,
    }


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
    include_math = True
    include_properties = True
    if filter.insight == "RETENTION" or filter.insight == "PATHS":
        return {}
    elif filter.insight == "LIFECYCLE":
        include_math = False
    return {
        "series": [
            entity_to_node(entity, include_properties, include_math)
            for entity in filter.entities
            if entity.id is not None
        ]
    }


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
        return {"properties": PropertyGroupFilter(**clean_properties(raw_properties))}
    else:
        return {"properties": PropertyGroupFilter(**clean_properties(raw_properties))}


def _breakdown_filter(_filter: AnyInsightFilter):
    if _filter.insight != "TRENDS" and _filter.insight != "FUNNELS":
        return {}

    # early return for broken breakdown filters
    if _filter.breakdown_type == "undefined" and not isinstance(_filter.breakdown, str):
        return {}

    breakdownFilter = {
        "breakdown_type": _filter.breakdown_type,
        "breakdown": _filter.breakdown,
        "breakdown_normalize_url": _filter.breakdown_normalize_url,
        "breakdown_group_type_index": _filter.breakdown_group_type_index,
        "breakdown_histogram_bin_count": _filter.breakdown_histogram_bin_count if _filter.insight == "TRENDS" else None,
    }

    if _filter.breakdowns is not None:
        if len(_filter.breakdowns) == 1:
            breakdownFilter["breakdown_type"] = _filter.breakdowns[0].get("type", None)
            breakdownFilter["breakdown"] = _filter.breakdowns[0].get("property", None)
        else:
            raise Exception("Could not convert multi-breakdown property `breakdowns` - found more than one breakdown")

    if breakdownFilter["breakdown"] is not None and breakdownFilter["breakdown_type"] is None:
        breakdownFilter["breakdown_type"] = "event"

    if isinstance(breakdownFilter["breakdown"], list):
        breakdownFilter["breakdown"] = list(filter(lambda x: x is not None, breakdownFilter["breakdown"]))

    return {"breakdown": BreakdownFilter(**breakdownFilter)}


def _group_aggregation_filter(filter: AnyInsightFilter):
    if isinstance(filter, LegacyStickinessFilter):
        return {}
    return {"aggregation_group_type_index": filter.aggregation_group_type_index}


def _insight_filter(filter: AnyInsightFilter):
    if filter.insight == "TRENDS" and isinstance(filter, LegacyFilter):
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
                # shown_as=filter.shown_as,
                display=clean_display(filter.display),
                # show_values_on_series=filter.show_values_on_series,
                # show_percent_stack_view=filter.show_percent_stack_view,
            )
        }
    elif filter.insight == "FUNNELS" and isinstance(filter, LegacyFilter):
        return {
            "funnelsFilter": FunnelsFilter(
                funnel_viz_type=filter.funnel_viz_type,
                funnel_order_type=filter.funnel_order_type,
                funnel_from_step=filter.funnel_from_step,
                funnel_to_step=filter.funnel_to_step,
                funnel_window_interval_unit=filter.funnel_window_interval_unit,
                funnel_window_interval=filter.funnel_window_interval,
                # funnel_step_reference=filter.funnel_step_reference,
                breakdown_attribution_type=filter.breakdown_attribution_type,
                breakdown_attribution_value=filter.breakdown_attribution_value,
                bin_count=filter.bin_count,
                exclusions=[
                    FunnelExclusion(
                        **to_base_entity_dict(entity),
                        funnel_from_step=entity.funnel_from_step,
                        funnel_to_step=entity.funnel_to_step,
                    )
                    for entity in filter.exclusions
                ],
                layout=filter.layout,
                # hidden_legend_breakdowns: cleanHiddenLegendSeries(filters.hidden_legend_keys),
                funnel_aggregate_by_hogql=filter.funnel_aggregate_by_hogql,
            ),
        }
    elif filter.insight == "RETENTION" and isinstance(filter, LegacyRetentionFilter):
        return {
            "retentionFilter": RetentionFilter(
                retention_type=filter.retention_type,
                # retention_reference=filter.retention_reference,
                total_intervals=filter.total_intervals,
                returning_entity=to_base_entity_dict(filter.returning_entity),
                target_entity=to_base_entity_dict(filter.target_entity),
                period=filter.period,
            )
        }
    elif filter.insight == "PATHS" and isinstance(filter, LegacyPathFilter):
        return {
            "pathsFilter": PathsFilter(
                # path_type=filter.path_type, # legacy
                paths_hogql_expression=filter.paths_hogql_expression,
                include_event_types=filter._data.get("include_event_types"),
                start_point=filter.start_point,
                end_point=filter.end_point,
                path_groupings=filter.path_groupings,
                exclude_events=filter.exclude_events,
                step_limit=filter.step_limit,
                path_replacements=filter.path_replacements,
                local_path_cleaning_filters=filter.local_path_cleaning_filters,
                edge_limit=filter.edge_limit,
                min_edge_weight=filter.min_edge_weight,
                max_edge_weight=filter.max_edge_weight,
                funnel_paths=filter.funnel_paths,
                funnel_filter=filter._data.get("funnel_filter"),
            )
        }
    elif filter.insight == "LIFECYCLE":
        return {
            "lifecycleFilter": LifecycleFilter(
                # shown_as=filter.shown_as,
                # toggledLifecycles=filter.toggledLifecycles,
                # show_values_on_series=filter.show_values_on_series,
            )
        }
    elif filter.insight == "STICKINESS" and isinstance(filter, LegacyStickinessFilter):
        return {
            "stickinessFilter": StickinessFilter(
                compare=filter.compare,
                # shown_as=filter.shown_as,
                # show_legend=filter.show_legend,
                # hidden_legend_indexes: cleanHiddenLegendIndexes(filters.hidden_legend_keys),
                # show_values_on_series=filter.show_values_on_series,
            )
        }
    else:
        raise Exception(f"Invalid insight type {filter.insight}.")


def filter_to_query(filter: AnyInsightFilter) -> InsightQueryNode:
    if (filter.insight == "TRENDS" or filter.insight == "FUNNELS" or filter.insight == "LIFECYCLE") and isinstance(
        filter, LegacyFilter
    ):
        matching_filter_type = True
    elif filter.insight == "RETENTION" and isinstance(filter, LegacyRetentionFilter):
        matching_filter_type = True
    elif filter.insight == "PATHS" and isinstance(filter, LegacyPathFilter):
        matching_filter_type = True
    elif filter.insight == "STICKINESS" and isinstance(filter, LegacyStickinessFilter):
        matching_filter_type = True
    else:
        matching_filter_type = False

    if not matching_filter_type:
        raise Exception(f"Filter type {type(filter)} does not match insight type {filter.insight}")

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
