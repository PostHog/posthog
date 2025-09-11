import re
import copy
import json
from enum import StrEnum
from typing import Any, Literal, Optional, Union, cast

from pydantic import Field

from posthog.schema import (
    ActionsNode,
    BaseMathType,
    BreakdownFilter,
    ChartDisplayType,
    CompareFilter,
    DataWarehouseNode,
    DateRange,
    EventsNode,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
    FunnelPathsFilter,
    FunnelsFilter,
    FunnelsQuery,
    FunnelVizType,
    LifecycleFilter,
    LifecycleQuery,
    PathsFilter,
    PathsQuery,
    RetentionEntity,
    RetentionFilter,
    RetentionQuery,
    StickinessFilter,
    StickinessQuery,
    TrendsFilter,
    TrendsQuery,
)

from posthog.hogql_queries.legacy_compatibility.clean_properties import clean_entity_properties, clean_global_properties
from posthog.models.entity.entity import Entity as LegacyEntity
from posthog.types import InsightQueryNode
from posthog.utils import str_to_bool


class MathAvailability(StrEnum):
    Unavailable = ("Unavailable",)
    All = ("All",)
    ActorsOnly = "ActorsOnly"
    FunnelsOnly = "FunnelsOnly"


actors_only_math_types = [
    BaseMathType.DAU,
    BaseMathType.WEEKLY_ACTIVE,
    BaseMathType.MONTHLY_ACTIVE,
    "unique_group",
    "hogql",
]

funnels_math_types = [
    BaseMathType.FIRST_TIME_FOR_USER,
]


def is_entity_variable(item: Any) -> bool:
    return isinstance(item, str) and item.startswith("{") and item.endswith("}")


def clean_display(display: Optional[str]):
    if display not in [c.value for c in ChartDisplayType]:
        return None
    else:
        return display


# Converts `hidden_legend_keys` in trends and stickiness insights to an array of hidden indexes.
# Example: `{1: true, 2: false}` will become `[1]`.
#
# Note: `hidden_legend_keys` in funnel insights follow a different format.
def hidden_legend_keys_to_indexes(hidden_legend_keys: dict | None) -> list[int] | None:
    if hidden_legend_keys:
        return [int(k) for k, v in hidden_legend_keys.items() if re.match(r"^\d+$", str(k)) and v is True]

    return None


# Converts `hidden_legend_keys` in funnel insights to an array of hidden breakdowns.
# Example: `{Chrome: true, Firefox: false}` will become: `["Chrome"]`.
#
# Also handles pre-#12123 legacy format.
# Example: {`events/$pageview/0/Baseline`: true} will become `['Baseline']`.
#
# Note: `hidden_legend_keys` in trends and stickiness insights follow a different format.
def hidden_legend_keys_to_breakdowns(hidden_legend_keys: dict | None) -> list[str] | None:
    if hidden_legend_keys:
        transformed_keys = transform_legacy_hidden_legend_keys(hidden_legend_keys)
        return [k for k, v in transformed_keys.items() if not re.match(r"^\d+$", str(k)) and v is True]
    return None


# Transform pre-#12113 funnel series keys to the current more reliable format.
#
# Old: `${step.type}/${step.action_id}/${step.order}/${breakdownValues.join('_')}`
# New: `breakdownValues.join('::')`
#
# If you squint you'll notice this doesn't actually handle the .join() part, but that's fine,
# because that's only relevant for funnels with multiple breakdowns, and that hasn't been
# released to users at the point of the format change.
def transform_legacy_hidden_legend_keys(hidden_legend_keys):
    transformed_keys = {}
    for key, value in hidden_legend_keys.items():
        parts = str(key).split("/", 3)
        if len(parts) == 4 and parts[2].isdigit():  # old format match
            series_key = parts[3]
            # Don't override values for series if already set from a previously-seen old-format key
            if series_key not in transformed_keys:
                transformed_keys[series_key] = value
        else:
            transformed_keys[key] = value
    return transformed_keys


def legacy_entity_to_node(
    entity: LegacyEntity | str,
    include_properties: bool,
    math_availability: MathAvailability,
    allow_variables: bool = False,
) -> EventsNode | ActionsNode | DataWarehouseNode | str:
    if allow_variables and is_entity_variable(entity):
        return cast(str, entity)

    assert not isinstance(entity, str)

    """
    Takes a legacy entity and converts it into an EventsNode or ActionsNode.
    """
    shared: dict[str, Any] = {
        "name": entity.name,
        "custom_name": entity.custom_name,
    }

    if include_properties:
        shared = {
            **shared,
            "properties": clean_entity_properties(entity._data.get("properties", None)),
        }

    if math_availability != MathAvailability.Unavailable:
        #  only trends, funnels, and stickiness insights support math.
        #  funnels only support a single base math type: first time for user.
        #  transition to then default math for stickiness, when an unsupported math type is encountered.

        if (
            entity.math is not None
            and math_availability == MathAvailability.ActorsOnly
            and entity.math not in actors_only_math_types
        ):
            shared = {**shared, "math": BaseMathType.DAU}
        elif math_availability == MathAvailability.FunnelsOnly:
            # All other math types must be skipped for funnels
            if entity.math in funnels_math_types:
                shared = {**shared, "math": entity.math}
        else:
            shared = {
                **shared,
                "math": entity.math,
                "math_property": entity.math_property,
                "math_hogql": entity.math_hogql,
                "math_group_type_index": entity.math_group_type_index,
            }

    if entity.type == "actions":
        return ActionsNode(id=entity.id, **shared)
    elif entity.type == "data_warehouse":
        return DataWarehouseNode(
            id=entity.id,
            id_field=entity.id_field,
            distinct_id_field=entity.distinct_id_field,
            timestamp_field=entity.timestamp_field,
            table_name=entity.table_name,
            **shared,
        )
    else:
        return EventsNode(event=entity.id, **shared)


def exlusion_entity_to_node(entity) -> FunnelExclusionEventsNode | FunnelExclusionActionsNode:
    """
    Takes a legacy exclusion entity and converts it into an FunnelExclusionEventsNode or FunnelExclusionActionsNode.
    """
    base_entity = legacy_entity_to_node(
        LegacyEntity(entity), include_properties=False, math_availability=MathAvailability.Unavailable
    )
    assert isinstance(base_entity, EventsNode | ActionsNode)
    if isinstance(base_entity, EventsNode):
        return FunnelExclusionEventsNode(
            **base_entity.model_dump(),
            funnelFromStep=entity.get("funnel_from_step"),
            funnelToStep=entity.get("funnel_to_step"),
        )
    else:
        return FunnelExclusionActionsNode(
            **base_entity.model_dump(),
            funnelFromStep=entity.get("funnel_from_step"),
            funnelToStep=entity.get("funnel_to_step"),
        )


# TODO: remove this method that returns legacy entities
def to_base_entity_dict(entity: dict | str):
    if isinstance(entity, str):
        if is_entity_variable(entity):
            return entity
        raise ValueError("Expecting valid entity or template variable")

    return {
        "type": entity.get("type"),
        "id": entity.get("id"),
        "name": entity.get("name"),
        "custom_name": entity.get("custom_name"),
        "order": entity.get("order"),
    }


insight_to_query_type = {
    "TRENDS": TrendsQuery,
    "FUNNELS": FunnelsQuery,
    "RETENTION": RetentionQuery,
    "PATHS": PathsQuery,
    "LIFECYCLE": LifecycleQuery,
    "STICKINESS": StickinessQuery,
}


class TrendsQueryWithTemplateVariables(TrendsQuery):
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode, str]] = Field(  # type: ignore
        ..., description="Events and actions to include"
    )


class FunnelsQueryWithTemplateVariables(FunnelsQuery):
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode, str]] = Field(  # type: ignore
        ..., description="Events and actions to include"
    )


class RetentionFilterWithTemplateVariables(RetentionFilter):
    returningEntity: Optional[RetentionEntity | str] = None  # type: ignore
    targetEntity: Optional[RetentionEntity | str] = None  # type: ignore


class RetentionQueryWithTemplateVariables(RetentionQuery):
    retentionFilter: RetentionFilterWithTemplateVariables = Field(
        ..., description="Properties specific to the retention insight"
    )


class LifecycleQueryWithTemplateVariables(LifecycleQuery):
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode, str]] = Field(  # type: ignore
        ..., description="Events and actions to include"
    )


class StickinessQueryWithTemplateVariables(StickinessQuery):
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode, str]] = Field(  # type: ignore
        ..., description="Events and actions to include"
    )


#
insight_to_query_type_with_variables = {
    "TRENDS": TrendsQueryWithTemplateVariables,
    "FUNNELS": FunnelsQueryWithTemplateVariables,
    "RETENTION": RetentionQueryWithTemplateVariables,
    "PATHS": PathsQuery,
    "LIFECYCLE": LifecycleQueryWithTemplateVariables,
    "STICKINESS": StickinessQueryWithTemplateVariables,
}

INSIGHT_TYPE = Literal["TRENDS", "FUNNELS", "RETENTION", "PATHS", "LIFECYCLE", "STICKINESS"]


def _date_range(filter: dict):
    date_range = DateRange(
        date_from=filter.get("date_from"),
        date_to=filter.get("date_to"),
        explicitDate=str_to_bool(filter.get("explicit_date")) if filter.get("explicit_date") else None,
    )

    if len(date_range.model_dump(exclude_defaults=True)) == 0:
        return {}

    return {"dateRange": date_range}


def _interval(filter: dict):
    if _insight_type(filter) == "RETENTION" or _insight_type(filter) == "PATHS":
        return {}

    if filter.get("interval") == "minute":
        return {"interval": "hour"}

    return {"interval": filter.get("interval")}


def _series(filter: dict, allow_variables: bool = False):
    if _insight_type(filter) == "RETENTION" or _insight_type(filter) == "PATHS":
        return {}

    # remove templates gone wrong
    if not allow_variables and filter.get("events") is not None:
        filter["events"] = [event for event in (filter.get("events") or []) if not (isinstance(event, str))]

    math_availability: MathAvailability = MathAvailability.Unavailable
    include_properties: bool = True

    if _insight_type(filter) == "TRENDS":
        math_availability = MathAvailability.All
    if _insight_type(filter) == "FUNNELS":
        math_availability = MathAvailability.FunnelsOnly
    elif _insight_type(filter) == "STICKINESS":
        math_availability = MathAvailability.ActorsOnly

    return {
        "series": [
            legacy_entity_to_node(entity, include_properties, math_availability, allow_variables)
            for entity in _entities(filter, allow_variables)
            if isinstance(entity, str) or not (entity.type == "actions" and entity.id is None)
        ]
    }


def _entities(filter: dict, allow_variables: bool = False):
    processed_entities: list[LegacyEntity | str] = []
    has_variables = False

    # add actions
    actions = filter.get("actions", [])
    if isinstance(actions, str):
        actions = json.loads(actions)
    processed_entities.extend([LegacyEntity({**entity, "type": "actions"}) for entity in actions])

    # add events
    events = filter.get("events", [])
    if isinstance(events, str):
        events = json.loads(events)

    def process_event(entity) -> LegacyEntity | str:
        nonlocal has_variables

        # strings represent template variables, return them as-is
        if allow_variables and isinstance(entity, str):
            has_variables = True
            return entity
        else:
            return LegacyEntity({**entity, "type": "events"})

    processed_entities.extend([process_event(entity) for entity in events])

    # add data warehouse
    warehouse = filter.get("data_warehouse", [])
    if isinstance(warehouse, str):
        warehouse = json.loads(warehouse)
    processed_entities.extend([LegacyEntity({**entity, "type": "data_warehouse"}) for entity in warehouse])

    if not has_variables:
        # order by order
        processed_entities.sort(key=lambda entity: entity.order if entity.order else -1)  # type: ignore

        # set sequential index values on entities
        for index, entity in enumerate(processed_entities):
            entity.index = index  # type: ignore

    return processed_entities


def _sampling_factor(filter: dict):
    if isinstance(filter.get("sampling_factor"), str):
        try:
            return {"samplingFactor": float(filter.get("sampling_factor"))}  # type: ignore
        except (ValueError, TypeError):
            return {}
    else:
        return {"samplingFactor": filter.get("sampling_factor")}


def _properties(filter: dict):
    raw_properties = filter.get("properties", None)
    return {"properties": clean_global_properties(raw_properties)}


def _filter_test_accounts(filter: dict):
    return {"filterTestAccounts": filter.get("filter_test_accounts")}


def _breakdown_filter(_filter: dict):
    if _insight_type(_filter) != "TRENDS" and _insight_type(_filter) != "FUNNELS":
        return {}

    # early return for broken breakdown filters
    if _filter.get("breakdown_type") == "undefined" and not isinstance(_filter.get("breakdown"), str):
        return {}

    breakdownFilter = {
        "breakdown_type": _filter.get("breakdown_type"),
        "breakdown": _filter.get("breakdown"),
        "breakdown_normalize_url": _filter.get("breakdown_normalize_url"),
        "breakdown_group_type_index": _filter.get("breakdown_group_type_index"),
        "breakdown_hide_other_aggregation": _filter.get("breakdown_hide_other_aggregation"),
        "breakdown_histogram_bin_count": (
            _filter.get("breakdown_histogram_bin_count") if _insight_type(_filter) == "TRENDS" else None
        ),
        "breakdown_limit": _filter.get("breakdown_limit"),
    }

    # fix breakdown typo
    if breakdownFilter["breakdown_type"] == "events":
        breakdownFilter["breakdown_type"] = "event"

    if _filter.get("breakdowns") is not None:
        if _insight_type(_filter) == "TRENDS":
            # Trends support multiple breakdowns
            breakdowns = []
            for breakdown in _filter["breakdowns"]:
                if isinstance(breakdown, dict) and "property" in breakdown:
                    breakdowns.append(
                        {
                            "type": breakdown.get("type", "event"),
                            "property": breakdown.get("property"),
                            "normalize_url": breakdown.get("normalize_url", None),
                            "histogram_bin_count": breakdown.get("histogram_bin_count", None),
                            "group_type_index": breakdown.get("group_type_index", None),
                        }
                    )

            if len(breakdowns) > 0:
                # Multiple breakdowns accept up to three breakdowns
                breakdownFilter["breakdowns"] = breakdowns[:3]
        else:
            if isinstance(_filter["breakdowns"], list) and len(_filter["breakdowns"]) == 1:
                breakdownFilter["breakdown_type"] = _filter["breakdowns"][0].get("type", None)
                breakdownFilter["breakdown"] = _filter["breakdowns"][0].get("property", None)
            else:
                raise Exception(
                    "Could not convert multi-breakdown property `breakdowns` - found more than one breakdown"
                )

    if breakdownFilter["breakdown"] is not None and breakdownFilter["breakdown_type"] is None:
        breakdownFilter["breakdown_type"] = "event"

    if isinstance(breakdownFilter["breakdown"], list):
        breakdownFilter["breakdown"] = list(filter(lambda x: x is not None, breakdownFilter["breakdown"]))

    if len(BreakdownFilter(**breakdownFilter).model_dump(exclude_defaults=True)) == 0:
        return {}

    return {"breakdownFilter": BreakdownFilter(**breakdownFilter)}


def _compare_filter(_filter: dict):
    if _insight_type(_filter) != "TRENDS" and _insight_type(_filter) != "STICKINESS":
        return {}

    compareFilter = {
        "compare": _filter.get("compare"),
        "compare_to": _filter.get("compare_to"),
    }

    if len(CompareFilter(**compareFilter).model_dump(exclude_defaults=True)) == 0:
        return {}

    return {"compareFilter": CompareFilter(**compareFilter)}


def _group_aggregation_filter(filter: dict):
    if _insight_type(filter) == "STICKINESS" or _insight_type(filter) == "LIFECYCLE":
        return {}
    return {"aggregation_group_type_index": filter.get("aggregation_group_type_index")}


def _insight_filter(filter: dict, allow_variables: bool = False):
    if _insight_type(filter) == "TRENDS":
        insight_filter = {
            "trendsFilter": TrendsFilter(
                smoothingIntervals=filter.get("smoothing_intervals"),
                showLegend=filter.get("show_legend"),
                showAlertThresholdLines=filter.get("show_alert_threshold_lines"),
                hiddenLegendIndexes=hidden_legend_keys_to_indexes(filter.get("hidden_legend_keys")),
                aggregationAxisFormat=filter.get("aggregation_axis_format"),
                aggregationAxisPrefix=filter.get("aggregation_axis_prefix"),
                aggregationAxisPostfix=filter.get("aggregation_axis_postfix"),
                decimalPlaces=filter.get("decimal_places"),
                formula=filter.get("formula"),
                display=clean_display(filter.get("display")),
                showValuesOnSeries=filter.get("show_values_on_series"),
                showPercentStackView=filter.get("show_percent_stack_view"),
                showLabelsOnSeries=filter.get("show_label_on_series"),
                yAxisScaleType=filter.get("y_axis_scale_type"),
                showMultipleYAxes=filter.get("show_multiple_y_axes"),
            )
        }
    elif _insight_type(filter) == "FUNNELS":
        funnel_viz_type = filter.get("funnel_viz_type")
        # Backwards compatibility
        # Before Filter.funnel_viz_type funnel trends were indicated by Filter.display being TRENDS_LINEAR
        if funnel_viz_type is None and filter.get("display") == "ActionsLineGraph":
            funnel_viz_type = FunnelVizType.TRENDS

        insight_filter = {
            "funnelsFilter": FunnelsFilter(
                funnelVizType=funnel_viz_type,
                funnelOrderType=filter.get("funnel_order_type"),
                funnelFromStep=filter.get("funnel_from_step"),
                funnelToStep=filter.get("funnel_to_step"),
                funnelWindowIntervalUnit=filter.get("funnel_window_interval_unit"),
                funnelWindowInterval=filter.get("funnel_window_interval"),
                funnelStepReference=filter.get("funnel_step_reference"),
                breakdownAttributionType=filter.get("breakdown_attribution_type"),
                breakdownAttributionValue=filter.get("breakdown_attribution_value"),
                binCount=filter.get("bin_count"),
                exclusions=[exlusion_entity_to_node(entity) for entity in filter.get("exclusions", [])],
                layout=filter.get("layout"),
                hiddenLegendBreakdowns=hidden_legend_keys_to_breakdowns(filter.get("hidden_legend_keys")),
                funnelAggregateByHogQL=filter.get("funnel_aggregate_by_hogql"),
            ),
        }
    elif _insight_type(filter) == "RETENTION":
        RetentionFilterClass = RetentionFilterWithTemplateVariables if allow_variables else RetentionFilter
        insight_filter = {
            "retentionFilter": RetentionFilterClass(
                retentionType=filter.get("retention_type"),
                retentionReference=filter.get("retention_reference"),
                totalIntervals=filter.get("total_intervals"),
                returningEntity=(
                    to_base_entity_dict(filter.get("returning_entity"))  # type: ignore
                    if filter.get("returning_entity") is not None
                    else None
                ),
                targetEntity=(
                    to_base_entity_dict(filter.get("target_entity"))  # type: ignore
                    if filter.get("target_entity") is not None
                    else None
                ),
                period=filter.get("period"),
                meanRetentionCalculation=filter.get("mean_retention_calculation")
                or ("simple" if filter.get("show_mean") else "none" if filter.get("show_mean") is False else "simple"),
                cumulative=filter.get("cumulative"),
            )
        }
    elif _insight_type(filter) == "PATHS":
        insight_filter = {
            "pathsFilter": PathsFilter(
                pathsHogQLExpression=filter.get("paths_hogql_expression"),
                includeEventTypes=filter.get("include_event_types"),
                startPoint=filter.get("start_point"),
                endPoint=filter.get("end_point"),
                pathGroupings=filter.get("path_groupings"),
                excludeEvents=filter.get("exclude_events"),
                stepLimit=filter.get("step_limit"),
                pathReplacements=filter.get("path_replacements"),
                localPathCleaningFilters=filter.get("local_path_cleaning_filters"),
                edgeLimit=filter.get("edge_limit"),
                minEdgeWeight=filter.get("min_edge_weight"),
                maxEdgeWeight=filter.get("max_edge_weight"),
            ),
            "funnelPathsFilter": filters_to_funnel_paths_query(filter),  # type: ignore
        }
    elif _insight_type(filter) == "LIFECYCLE":
        insight_filter = {
            "lifecycleFilter": LifecycleFilter(
                toggledLifecycles=filter.get("toggledLifecycles"),
                showLegend=filter.get("show_legend"),
                showValuesOnSeries=filter.get("show_values_on_series"),
            )
        }
    elif _insight_type(filter) == "STICKINESS":
        insight_filter = {
            "stickinessFilter": StickinessFilter(
                showLegend=filter.get("show_legend"),
                hiddenLegendIndexes=hidden_legend_keys_to_indexes(filter.get("hidden_legend_keys")),
                showValuesOnSeries=filter.get("show_values_on_series"),
            )
        }
    else:
        raise Exception(f"Invalid insight type {filter.get('insight')}.")

    if len(next(iter(insight_filter.values())).model_dump(exclude_defaults=True)) == 0:
        return {}

    return insight_filter


def filters_to_funnel_paths_query(filter: dict[str, Any]) -> FunnelPathsFilter | None:
    funnel_paths = filter.get("funnel_paths")
    funnel_filter = filter.get("funnel_filter")

    if funnel_paths is None or funnel_filter is None:
        return None

    funnel_query = filter_to_query(funnel_filter)
    assert isinstance(funnel_query, FunnelsQuery)

    return FunnelPathsFilter(
        funnelPathType=funnel_paths,
        funnelSource=funnel_query,
        funnelStep=funnel_filter["funnel_step"],
    )


def _insight_type(filter: dict) -> INSIGHT_TYPE:
    if filter.get("shown_as") == "Stickiness":
        return "STICKINESS"
    elif filter.get("insight") == "SESSIONS":
        return "TRENDS"
    return filter.get("insight", "TRENDS")


def filter_to_query(filter: dict, allow_variables: bool = False) -> InsightQueryNode:
    filter = copy.deepcopy(filter)  # duplicate to prevent accidental filter alterations

    Query = (
        insight_to_query_type_with_variables[_insight_type(filter)]
        if allow_variables
        else insight_to_query_type[_insight_type(filter)]
    )

    data = {
        **_date_range(filter),
        **_interval(filter),
        **_series(filter, allow_variables),
        **_sampling_factor(filter),
        **_filter_test_accounts(filter),
        **_properties(filter),
        **_breakdown_filter(filter),
        **_compare_filter(filter),
        **_group_aggregation_filter(filter),
        **_insight_filter(filter, allow_variables),
    }

    # :KLUDGE: We do this dance to have default values instead of None, when setting
    # values from a filter above.
    return Query(**Query(**data).model_dump(exclude_none=True))


def filter_str_to_query(filters: str) -> InsightQueryNode:
    filter = json.loads(filters)
    # we have insights that have been serialized to json twice in the database
    # due to people misunderstanding our api
    if isinstance(filter, str):
        filter = json.loads(filter)
    # we also have insights wrapped in an additional array
    elif isinstance(filter, list):
        filter = filter[0]
    return filter_to_query(filter)
