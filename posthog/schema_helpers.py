import orjson
from typing import Any, Literal, get_origin
from pydantic import BaseModel, ValidationError, model_serializer
from rest_framework.utils.encoders import JSONEncoder

from posthog.schema import (
    ChartDisplayType,
    FunnelsQuery,
    LifecycleQuery,
    PathsQuery,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
)
from posthog.types import InsightQueryNode


def to_dict(query: BaseModel) -> dict:
    klass: Any = type(query)

    class ExtendedQuery(klass):
        @model_serializer(mode="wrap")
        def serialize_query(self, next_serializer):
            dumped = next_serializer(self)

            ###
            # Our schema is generated with `Literal` fields for type, kind, etc. These
            # are stripped by the `exclude_defaults=True` option, so we add them back in
            # here.
            for name, field_info in self.model_fields.items():
                if get_origin(field_info.annotation) == Literal:
                    dumped[name] = getattr(self, name)

            if isinstance(
                self,
                (TrendsQuery | FunnelsQuery | RetentionQuery | PathsQuery | StickinessQuery | LifecycleQuery),
            ):
                insightFilterKey = filter_key_for_query(self)

                for name in self.model_fields.keys():
                    if name not in dumped:
                        continue

                    ###
                    # Frontend only settings like which graph type is displayed, that don't affect
                    # the generated dataset should be removed.
                    #
                    # Keep this in sync with the frontend side "cleanInsightQuery" function.
                    if name == "series":
                        # remove frontend-only props from series
                        dumped["series"] = [
                            {key: value for key, value in entity.items() if key != "custom_name"}
                            for entity in dumped["series"]
                        ]
                    elif name == insightFilterKey:
                        # remove frontend-only props from insight filters
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
                                "yAxisScaleType",
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

    # our schema is generated, so extend the models here
    query = ExtendedQuery(**query.model_dump())

    # generate a dict from the pydantic model
    instance_dict = query.model_dump(exclude_none=True, exclude_defaults=True)

    return instance_dict


def to_json(obj: dict) -> bytes:
    # pydantic doesn't sort keys reliably, so use orjson to serialize to json
    option = orjson.OPT_SORT_KEYS
    json_string = orjson.dumps(obj, default=JSONEncoder().default, option=option)

    return json_string


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
