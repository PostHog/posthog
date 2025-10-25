from typing import Literal, get_origin

from pydantic import BaseModel, ValidationError

from posthog.schema import (
    BaseMathType,
    ChartDisplayType,
    FunnelsQuery,
    LifecycleQuery,
    PathsQuery,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
)

from posthog.hogql_queries.insights.utils.utils import series_should_be_set_to_dau
from posthog.types import InsightQueryNode


def strip_version_recursive(d):
    if not isinstance(d, dict):
        return d

    if "version" in d:
        del d["version"]

    for key, value in d.items():
        if isinstance(value, dict):
            d[key] = strip_version_recursive(value)
        elif isinstance(value, list):
            d[key] = [strip_version_recursive(item) if isinstance(item, dict) else item for item in value]

    return d


def to_dict(query: BaseModel) -> dict:
    dumped = query.model_dump(exclude_none=True, exclude_defaults=True)
    dumped = strip_version_recursive(dumped)

    ###
    # Our schema is generated with `Literal` fields for type, kind, etc. These
    # are stripped by the `exclude_defaults=True` option, so we add them back in
    # here.
    for name, field_info in query.model_fields.items():
        if get_origin(field_info.annotation) == Literal:
            dumped[name] = getattr(query, name)

    if isinstance(
        query,
        (TrendsQuery | FunnelsQuery | RetentionQuery | PathsQuery | StickinessQuery | LifecycleQuery),
    ):
        insightFilterKey = filter_key_for_query(query)

        for name in query.model_fields.keys():
            if name not in dumped:
                continue

            ###
            # Frontend only settings like which graph type is displayed, that don't affect
            # the generated dataset should be removed.
            #
            # Keep this in sync with the frontend side "cleanInsightQuery" function.
            if name == "series":
                # remove frontend-only props from series
                # Only TrendsQuery, FunnelsQuery, StickinessQuery, and LifecycleQuery have series
                if hasattr(query, "series"):
                    new_series_list = []
                    for dumped_series, series in zip(dumped[name], query.series):
                        new_series = {key: value for key, value in dumped_series.items() if key != "custom_name"}
                        if (
                            isinstance(query, TrendsQuery)
                            and query.interval is not None
                            and series_should_be_set_to_dau(query.interval, series)
                        ):
                            new_series["math"] = BaseMathType.DAU
                        new_series_list.append(new_series)
                    dumped["series"] = new_series_list
            elif name == insightFilterKey:
                # Remove frontend-only props from insight filters
                # Keep this in sync with frontend/src/scenes/insights/utils/queryUtils.ts `cleanInsightQuery` method
                dumped[insightFilterKey] = {
                    key: value
                    for key, value in dumped[insightFilterKey].items()
                    if key
                    not in [
                        "showLegend",
                        "showPercentStackView",
                        "showValuesOnSeries",
                        "aggregationAxisFormat",
                        "aggregationAxisPrefix",
                        "aggregationAxisPostfix",
                        "decimalPlaces",
                        "layout",
                        "toggledLifecycles",
                        "showLabelsOnSeries",
                        "showMean",
                        "meanRetentionCalculation",
                        "yAxisScaleType",
                        "hiddenLegendIndexes",
                        "hiddenLegendBreakdowns",
                        "resultCustomizations",
                        "resultCustomizationBy",
                        "goalLines",
                        "dashboardDisplay",
                        "showConfidenceIntervals",
                        "confidenceLevel",
                        "showTrendLines",
                        "showMovingAverage",
                        "movingAverageIntervals",
                        "stacked",
                        "detailedResultsAggregationType",
                        "showFullUrls",
                    ]
                }

                for key in ("targetEntity", "returningEntity"):
                    if key in dumped[insightFilterKey] and "uuid" in dumped[insightFilterKey][key]:
                        del dumped[insightFilterKey][key]["uuid"]

                # use a canonical value for each display category
                if "display" in dumped[insightFilterKey]:
                    canonical_display = grouped_chart_display_types(dumped[insightFilterKey]["display"])
                    if canonical_display == ChartDisplayType.ACTIONS_LINE_GRAPH:
                        del dumped[insightFilterKey]["display"]  # default value, remove
                    else:
                        dumped[insightFilterKey]["display"] = canonical_display

            ###
            # Remove empty nested models, so that empty and not existing models serialize to the same json.
            filterKeys = [insightFilterKey, "breakdownFilter", "dateRange"]
            if name in filterKeys and len(dumped[name]) == 0:
                del dumped[name]

    return dumped


def filter_key_for_query(node: InsightQueryNode) -> str:
    if isinstance(node, TrendsQuery):
        return "trendsFilter"
    elif isinstance(node, FunnelsQuery):
        return "funnelsFilter"
    elif isinstance(node, RetentionQuery):
        return "retentionFilter"
    elif isinstance(node, PathsQuery):
        return "pathsFilter"
    elif isinstance(node, StickinessQuery):
        return "stickinessFilter"
    elif isinstance(node, LifecycleQuery):
        return "lifecycleFilter"
    else:
        raise ValidationError(f"Expected an insight node, got {node.__name__}")


def grouped_chart_display_types(display: ChartDisplayType) -> ChartDisplayType | None:
    if display in [
        ChartDisplayType.ACTIONS_LINE_GRAPH,
        ChartDisplayType.ACTIONS_BAR,
        ChartDisplayType.ACTIONS_AREA_GRAPH,
    ]:
        # time series
        return ChartDisplayType.ACTIONS_LINE_GRAPH
    elif display in [ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE]:
        # cumulative time series
        return ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE
    else:
        # total value
        return ChartDisplayType.ACTIONS_BAR_VALUE
