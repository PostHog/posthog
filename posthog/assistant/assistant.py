import json
from datetime import timedelta
from functools import cached_property
from typing import Any

import openai
from django.utils import timezone
from pydantic import BaseModel

from posthog.models.action.action import Action
from posthog.models.event_definition import EventDefinition
from posthog.models.property_definition import PropertyDefinition
from posthog.models.team.team import Team
from posthog.schema import TrendsQuery

from .hardcoded_definitions import hardcoded_prop_defs

system_prompt = """
As a recognized head of product growth acting as a top-tier data engineer, your task is to write queries of trends insights for customers using a JSON schema.

Follow these instructions to create a query:
* Identify the events or actions the user wants to analyze.
* Determine a vistualization type that best suits the user's needs.
* Determine if the user wants to name the series or use the default names.
* Choose the date range and the interval the user wants to analyze.
* Determine if the user wants to compare the results to a previous period or use smoothing.
* Determine if the user wants to use property filters for all series.
* Determine math types for all series.
* Determine property filters for individual series.
* Determine if the user wants to use a breakdown filter.
* Determine if the user wants to filter out internal and test users. If the user didn't specify, filter out internal and test users by default.
* Determine if the user wants to use sampling factor.
* Determine if it's useful to show a legend, values of series, units, y-axis scale type, etc.
* Use your judgement if there are any other parameters that the user might want to adjust that aren't listed here.

{trends_description}

For your reference, there is a description of the data model.

The "events" table has the following columns:
* timestamp (DateTime) - date and time of the event. Events are sorted by timestamp in ascending order.
* uuid (UUID) - unique identifier of the event.
* person_id (UUID) - unique identifier of the person who performed the event.
* event (String) - name of the event.
* properties (custom type) - additional properties of the event. Properties can be of multiple types: String, Int, Decimal, Float, and Bool. A property can be an array of thosee types. A property always has only ONE type. If the property starts with a $, it is a system-defined property. If the property doesn't start with a $, it is a user-defined property. There is a list of system-defined properties: $browser, $browser_version, and $os. User-defined properties can have any name. If the property is not in the list of system properties, it IS a user-defined property.

{available_events}{available_actions}{available_properties}

Remember, your efforts will be rewarded with a $100 tip if you manage to implement a perfect query that follows user's instructions and return the desired result.
"""

instructions_prompt = """
Trends insights enable users to plot data from people, events, and properties however they want. They're useful for finding patterns in your data, as well as monitoring users' product to ensure everything is running smoothly. For example, using trends, users can analyze:
- How your most important metrics change over time.
- Long-term patterns, or cycles in your usage.
- How a specific change affects usage.
- The usage of different features side-by-side.
- How the properties of events vary using aggregation (sum, average, etc).
- You can also visualize the same data points in a variety of ways.

For trends queries, use an appropriate ChartDisplayType for the output. For example:
- if the user wants to see a dynamics in time like a line graph, use `ActionsLineGraph`.
- if the user wants to see cumulative dynamics across time, use `ActionsLineGraphCumulative`.
- if the user asks a question where you can answer with a single number, use `BoldNumber`.
- if the user wants a table, use `ActionsTable`.
- if the data is categorical, use `ActionsBar`.
- if the data is easy to understand in a pie chart, use `ActionsPie`.
- if the user has only one series and they want to see data from particular countries, use `WorldMap`.

Learn on these examples:
Q: How many users do I have?
A: {"dateRange":{"date_from":"all"},"interval":"month","kind":"TrendsQuery","series":[{"event":"user signed up","kind":"EventsNode","math":"total"}],"trendsFilter":{"aggregationAxisFormat":"numeric","display":"BoldNumber"}}
Q: Show a bar chart of the organic search traffic for the last month grouped by week.
A: {"dateRange":{"date_from":"-30d","date_to":null,"explicitDate":false},"interval":"week","kind":"TrendsQuery","series":[{"event":"$pageview","kind":"EventsNode","math":"dau","properties":[{"key":"$referring_domain","operator":"icontains","type":"event","value":"google"},{"key":"utm_source","operator":"is_not_set","type":"event","value":"is_not_set"}]}],"trendsFilter":{"aggregationAxisFormat":"numeric","display":"ActionsBar"}}
Q: insight created unique users & first-time users for the last 12m)
A: {"dateRange":{"date_from":"-12m","date_to":""},"filterTestAccounts":true,"interval":"month","kind":"TrendsQuery","series":[{"event":"insight created","kind":"EventsNode","math":"dau","custom_name":"insight created"},{"event":"insight created","kind":"EventsNode","math":"first_time_for_user","custom_name":"insight created"}],"trendsFilter":{"aggregationAxisFormat":"numeric","display":"ActionsLineGraph"}}
Q: What are the top 10 referring domains for the last month?
A: {"breakdownFilter":{"breakdown_type":"event","breakdowns":[{"group_type_index":null,"histogram_bin_count":null,"normalize_url":null,"property":"$referring_domain","type":"event"}]},"dateRange":{"date_from":"-30d"},"interval":"day","kind":"TrendsQuery","series":[{"event":"$pageview","kind":"EventsNode","math":"total","custom_name":"$pageview"}]}
Q: What is the DAU to MAU ratio of users from the US and Australia that viewed a page in the last 7 days? Compare it to the previous period.
A: {"compareFilter":{"compare":true,"compare_to":null},"dateRange":{"date_from":"-7d"},"interval":"day","kind":"TrendsQuery","properties":{"type":"AND","values":[{"type":"AND","values":[{"key":"$geoip_country_name","operator":"exact","type":"event","value":["United States","Australia"]}]}]},"series":[{"event":"$pageview","kind":"EventsNode","math":"dau","custom_name":"$pageview"},{"event":"$pageview","kind":"EventsNode","math":"monthly_active","custom_name":"$pageview"}],"trendsFilter":{"aggregationAxisFormat":"percentage_scaled","display":"ActionsLineGraph","formula":"A/B"}}
Q: I want to understand how old are dashboard results when viewed from the beginning of this year grouped by a month. Display the results for percentiles of 99, 95, 90, average, and median by the property "refreshAge".
A: {"dateRange":{"date_from":"yStart","date_to":null,"explicitDate":false},"filterTestAccounts":true,"interval":"month","kind":"TrendsQuery","series":[{"event":"viewed dashboard","kind":"EventsNode","math":"p99","math_property":"refreshAge","custom_name":"viewed dashboard"},{"event":"viewed dashboard","kind":"EventsNode","math":"p95","math_property":"refreshAge","custom_name":"viewed dashboard"},{"event":"viewed dashboard","kind":"EventsNode","math":"p90","math_property":"refreshAge","custom_name":"viewed dashboard"},{"event":"viewed dashboard","kind":"EventsNode","math":"avg","math_property":"refreshAge","custom_name":"viewed dashboard"},{"event":"viewed dashboard","kind":"EventsNode","math":"median","math_property":"refreshAge","custom_name":"viewed dashboard"}],"trendsFilter":{"aggregationAxisFormat":"duration","display":"ActionsLineGraph"}}

Follow these rules:
- if the date range is not specified, use the best judgement to select a reasonable date range. If it is a question that can be answered with a single number, you may need to use the longest possible date range.
- Filter internal users by default if the user doesn't specify.
"""

hardcoded_schema = '{"$defs": {"ActionsNode": {"additionalProperties": false, "properties": {"custom_name": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "description": "Optional custom name for the node if the user asks for it", "title": "Custom Name"}, "id": {"description": "The ID of the action", "title": "Id", "type": "integer"}, "kind": {"const": "ActionsNode", "default": "ActionsNode", "enum": ["ActionsNode"], "title": "Kind", "type": "string"}, "properties": {"anyOf": [{"items": {"anyOf": [{"$ref": "#/$defs/EventPropertyFilter"}, {"$ref": "#/$defs/PersonPropertyFilter"}, {"$ref": "#/$defs/ElementPropertyFilter"}, {"$ref": "#/$defs/SessionPropertyFilter"}, {"$ref": "#/$defs/CohortPropertyFilter"}, {"$ref": "#/$defs/RecordingPropertyFilter"}, {"$ref": "#/$defs/FeaturePropertyFilter"}, {"$ref": "#/$defs/EmptyPropertyFilter"}]}, "type": "array"}, {"type": "null"}], "default": null, "description": "Filter series by properties", "title": "Properties"}, "response": {"anyOf": [{"type": "object"}, {"type": "null"}], "default": null, "title": "Response"}, "math": {"anyOf": [{"$ref": "#/$defs/BaseMathType"}, {"$ref": "#/$defs/CountPerActorMathType"}, {"$ref": "#/$defs/PropertyMathType"}, {"type": "null"}], "default": null, "description": "Aggregation type", "title": "Math"}, "math_property": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "description": "Event property to aggregate", "title": "Math Property"}}, "required": ["id"], "title": "ActionsNode", "type": "object"}, "AggregationAxisFormat": {"enum": ["numeric", "duration", "duration_ms", "percentage", "percentage_scaled"], "title": "AggregationAxisFormat", "type": "string"}, "BaseMathType": {"enum": ["total", "dau", "weekly_active", "monthly_active", "unique_session", "first_time_for_user"], "title": "BaseMathType", "type": "string"}, "Breakdown": {"additionalProperties": false, "properties": {"group_type_index": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": null, "title": "Group Type Index"}, "histogram_bin_count": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": null, "title": "Histogram Bin Count"}, "normalize_url": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": null, "title": "Normalize Url"}, "property": {"title": "Property", "type": "string"}, "type": {"anyOf": [{"$ref": "#/$defs/MultipleBreakdownType"}, {"type": "null"}], "default": null}}, "required": ["property"], "title": "Breakdown", "type": "object"}, "BreakdownFilter": {"additionalProperties": false, "properties": {"breakdown": {"anyOf": [{"type": "string"}, {"type": "integer"}, {"items": {"anyOf": [{"type": "string"}, {"type": "integer"}]}, "type": "array"}, {"type": "null"}], "default": null, "title": "Breakdown"}, "breakdown_group_type_index": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": null, "title": "Breakdown Group Type Index"}, "breakdown_hide_other_aggregation": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": null, "title": "Breakdown Hide Other Aggregation"}, "breakdown_histogram_bin_count": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": null, "title": "Breakdown Histogram Bin Count"}, "breakdown_limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": null, "title": "Breakdown Limit"}, "breakdown_normalize_url": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": null, "title": "Breakdown Normalize Url"}, "breakdown_type": {"anyOf": [{"$ref": "#/$defs/BreakdownType"}, {"type": "null"}], "default": "event"}, "breakdowns": {"anyOf": [{"items": {"$ref": "#/$defs/Breakdown"}, "maxItems": 3, "type": "array"}, {"type": "null"}], "default": null, "title": "Breakdowns"}}, "title": "BreakdownFilter", "type": "object"}, "BreakdownType": {"enum": ["cohort", "person", "event", "group", "session"], "title": "BreakdownType", "type": "string"}, "ChartDisplayType": {"enum": ["ActionsLineGraph", "ActionsBar", "ActionsStackedBar", "ActionsAreaGraph", "ActionsLineGraphCumulative", "BoldNumber", "ActionsPie", "ActionsBarValue", "ActionsTable", "WorldMap"], "title": "ChartDisplayType", "type": "string"}, "CohortPropertyFilter": {"additionalProperties": false, "properties": {"key": {"const": "id", "default": "id", "enum": ["id"], "title": "Key", "type": "string"}, "label": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Label"}, "type": {"const": "cohort", "default": "cohort", "enum": ["cohort"], "title": "Type", "type": "string"}, "value": {"title": "Value", "type": "integer"}}, "required": ["value"], "title": "CohortPropertyFilter", "type": "object"}, "CompareFilter": {"additionalProperties": false, "properties": {"compare": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": null, "title": "Compare"}, "compare_to": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Compare To"}}, "title": "CompareFilter", "type": "object"}, "CountPerActorMathType": {"enum": ["avg_count_per_actor", "min_count_per_actor", "max_count_per_actor", "median_count_per_actor", "p90_count_per_actor", "p95_count_per_actor", "p99_count_per_actor"], "title": "CountPerActorMathType", "type": "string"}, "DurationType": {"enum": ["duration", "active_seconds", "inactive_seconds"], "title": "DurationType", "type": "string"}, "ElementPropertyFilter": {"additionalProperties": false, "properties": {"key": {"$ref": "#/$defs/Key"}, "label": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Label"}, "operator": {"$ref": "#/$defs/PropertyOperator"}, "type": {"const": "element", "default": "element", "enum": ["element"], "title": "Type", "type": "string"}, "value": {"anyOf": [{"type": "string"}, {"type": "number"}, {"items": {"anyOf": [{"type": "string"}, {"type": "number"}]}, "type": "array"}, {"type": "null"}], "default": null, "title": "Value"}}, "required": ["key", "operator"], "title": "ElementPropertyFilter", "type": "object"}, "EmptyPropertyFilter": {"additionalProperties": false, "properties": {}, "title": "EmptyPropertyFilter", "type": "object"}, "EventPropertyFilter": {"additionalProperties": false, "properties": {"key": {"title": "Key", "type": "string"}, "label": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Label"}, "operator": {"anyOf": [{"$ref": "#/$defs/PropertyOperator"}, {"type": "null"}], "default": "exact"}, "type": {"const": "event", "default": "event", "description": "Event properties", "enum": ["event"], "title": "Type", "type": "string"}, "value": {"anyOf": [{"type": "string"}, {"type": "number"}, {"items": {"anyOf": [{"type": "string"}, {"type": "number"}]}, "type": "array"}, {"type": "null"}], "default": null, "title": "Value"}}, "required": ["key"], "title": "EventPropertyFilter", "type": "object"}, "EventsNode": {"additionalProperties": false, "properties": {"custom_name": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "description": "Optional custom name for the node if the user asks for it", "title": "Custom Name"}, "event": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "description": "The event or `null` for all events.", "title": "Event"}, "kind": {"const": "EventsNode", "default": "EventsNode", "enum": ["EventsNode"], "title": "Kind", "type": "string"}, "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": null, "title": "Limit"}, "orderBy": {"anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}], "default": null, "description": "Columns to order by", "title": "Orderby"}, "math": {"anyOf": [{"$ref": "#/$defs/BaseMathType"}, {"$ref": "#/$defs/CountPerActorMathType"}, {"$ref": "#/$defs/PropertyMathType"}, {"type": "null"}], "default": null, "description": "Aggregation type", "title": "Math"}, "math_property": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "description": "Event property to aggregate", "title": "Math Property"}, "properties": {"anyOf": [{"items": {"anyOf": [{"$ref": "#/$defs/EventPropertyFilter"}, {"$ref": "#/$defs/PersonPropertyFilter"}, {"$ref": "#/$defs/ElementPropertyFilter"}, {"$ref": "#/$defs/SessionPropertyFilter"}, {"$ref": "#/$defs/CohortPropertyFilter"}, {"$ref": "#/$defs/RecordingPropertyFilter"}, {"$ref": "#/$defs/FeaturePropertyFilter"}, {"$ref": "#/$defs/EmptyPropertyFilter"}]}, "type": "array"}, {"type": "null"}], "default": null, "description": "Properties to filter this series by", "title": "Properties"}}, "title": "EventsNode", "type": "object"}, "FeaturePropertyFilter": {"additionalProperties": false, "properties": {"key": {"title": "Key", "type": "string"}, "label": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Label"}, "operator": {"$ref": "#/$defs/PropertyOperator"}, "type": {"const": "feature", "default": "feature", "description": "Event property with "$feature/" prepended", "enum": ["feature"], "title": "Type", "type": "string"}, "value": {"anyOf": [{"type": "string"}, {"type": "number"}, {"items": {"anyOf": [{"type": "string"}, {"type": "number"}]}, "type": "array"}, {"type": "null"}], "default": null, "title": "Value"}}, "required": ["key", "operator"], "title": "FeaturePropertyFilter", "type": "object"}, "InsightDateRange": {"additionalProperties": false, "properties": {"date_from": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": "-7d", "title": "Date From"}, "date_to": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Date To"}, "explicitDate": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": false, "description": "Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of period.", "title": "Explicitdate"}}, "title": "InsightDateRange", "type": "object"}, "IntervalType": {"enum": ["minute", "hour", "day", "week", "month"], "title": "IntervalType", "type": "string"}, "Key": {"enum": ["tag_name", "text", "href", "selector"], "title": "Key", "type": "string"}, "MultipleBreakdownType": {"enum": ["person", "event", "group", "session", "hogql"], "title": "MultipleBreakdownType", "type": "string"}, "PersonPropertyFilter": {"additionalProperties": false, "properties": {"key": {"title": "Key", "type": "string"}, "label": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Label"}, "operator": {"$ref": "#/$defs/PropertyOperator"}, "type": {"const": "person", "default": "person", "description": "Person properties", "enum": ["person"], "title": "Type", "type": "string"}, "value": {"anyOf": [{"type": "string"}, {"type": "number"}, {"items": {"anyOf": [{"type": "string"}, {"type": "number"}]}, "type": "array"}, {"type": "null"}], "default": null, "title": "Value"}}, "required": ["key", "operator"], "title": "PersonPropertyFilter", "type": "object"}, "PropertyMathType": {"enum": ["avg", "sum", "min", "max", "median", "p90", "p95", "p99"], "title": "PropertyMathType", "type": "string"}, "PropertyOperator": {"enum": ["exact", "is_not", "icontains", "not_icontains", "regex", "not_regex", "gt", "gte", "lt", "lte", "is_set", "is_not_set", "is_date_exact", "is_date_before", "is_date_after", "between", "not_between", "min", "max"], "title": "PropertyOperator", "type": "string"}, "RecordingPropertyFilter": {"additionalProperties": false, "properties": {"key": {"anyOf": [{"$ref": "#/$defs/DurationType"}, {"type": "string"}], "title": "Key"}, "label": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Label"}, "operator": {"$ref": "#/$defs/PropertyOperator"}, "type": {"const": "recording", "default": "recording", "enum": ["recording"], "title": "Type", "type": "string"}, "value": {"anyOf": [{"type": "string"}, {"type": "number"}, {"items": {"anyOf": [{"type": "string"}, {"type": "number"}]}, "type": "array"}, {"type": "null"}], "default": null, "title": "Value"}}, "required": ["key", "operator"], "title": "RecordingPropertyFilter", "type": "object"}, "SessionPropertyFilter": {"additionalProperties": false, "properties": {"key": {"title": "Key", "type": "string"}, "label": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Label"}, "operator": {"$ref": "#/$defs/PropertyOperator"}, "type": {"const": "session", "default": "session", "enum": ["session"], "title": "Type", "type": "string"}, "value": {"anyOf": [{"type": "string"}, {"type": "number"}, {"items": {"anyOf": [{"type": "string"}, {"type": "number"}]}, "type": "array"}, {"type": "null"}], "default": null, "title": "Value"}}, "required": ["key", "operator"], "title": "SessionPropertyFilter", "type": "object"}, "TrendsFilter": {"additionalProperties": false, "properties": {"aggregationAxisFormat": {"anyOf": [{"$ref": "#/$defs/AggregationAxisFormat"}, {"type": "null"}], "default": "numeric"}, "aggregationAxisPostfix": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Aggregationaxispostfix"}, "aggregationAxisPrefix": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Aggregationaxisprefix"}, "breakdown_histogram_bin_count": {"anyOf": [{"type": "number"}, {"type": "null"}], "default": null, "title": "Breakdown Histogram Bin Count"}, "decimalPlaces": {"anyOf": [{"type": "number"}, {"type": "null"}], "default": null, "title": "Decimalplaces"}, "display": {"anyOf": [{"$ref": "#/$defs/ChartDisplayType"}, {"type": "null"}], "default": "ActionsLineGraph"}, "formula": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Formula"}, "hiddenLegendIndexes": {"anyOf": [{"items": {"type": "integer"}, "type": "array"}, {"type": "null"}], "default": null, "title": "Hiddenlegendindexes"}, "showLabelsOnSeries": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": null, "title": "Showlabelsonseries"}, "showLegend": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": false, "title": "Showlegend"}, "showPercentStackView": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": false, "title": "Showpercentstackview"}, "showValuesOnSeries": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": false, "title": "Showvaluesonseries"}, "smoothingIntervals": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": 1, "title": "Smoothingintervals"}, "yAxisScaleType": {"anyOf": [{"$ref": "#/$defs/YAxisScaleType"}, {"type": "null"}], "default": null}}, "title": "TrendsFilter", "type": "object"}, "YAxisScaleType": {"enum": ["log10", "linear"], "title": "YAxisScaleType", "type": "string"}}, "additionalProperties": false, "properties": {"breakdownFilter": {"anyOf": [{"$ref": "#/$defs/BreakdownFilter"}, {"type": "null"}], "default": null, "description": "Breakdown of the events and actions"}, "compareFilter": {"anyOf": [{"$ref": "#/$defs/CompareFilter"}, {"type": "null"}], "default": null, "description": "Compare to date range"}, "dateRange": {"anyOf": [{"$ref": "#/$defs/InsightDateRange"}, {"type": "null"}], "default": null, "description": "Date range for the query"}, "filterTestAccounts": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": false, "description": "Exclude internal and test users by applying the respective filters", "title": "Filtertestaccounts"}, "interval": {"anyOf": [{"$ref": "#/$defs/IntervalType"}, {"type": "null"}], "default": "day", "description": "Granularity of the response. Can be one of `hour`, `day`, `week` or `month`"}, "kind": {"const": "TrendsQuery", "default": "TrendsQuery", "enum": ["TrendsQuery"], "title": "Kind", "type": "string"}, "properties": {"anyOf": [{"items": {"anyOf": [{"$ref": "#/$defs/EventPropertyFilter"}, {"$ref": "#/$defs/PersonPropertyFilter"}, {"$ref": "#/$defs/ElementPropertyFilter"}, {"$ref": "#/$defs/SessionPropertyFilter"}, {"$ref": "#/$defs/CohortPropertyFilter"}, {"$ref": "#/$defs/RecordingPropertyFilter"}, {"$ref": "#/$defs/FeaturePropertyFilter"}, {"$ref": "#/$defs/EmptyPropertyFilter"}]}, "type": "array"}, {"type": "null"}], "default": [], "description": "Property filters for all series", "title": "Properties"}, "samplingFactor": {"anyOf": [{"type": "number"}, {"type": "null"}], "default": null, "description": "Sampling rate", "title": "Samplingfactor"}, "series": {"description": "Events and actions to include", "items": {"anyOf": [{"$ref": "#/$defs/EventsNode"}, {"$ref": "#/$defs/ActionsNode"}]}, "title": "Series", "type": "array"}, "trendsFilter": {"anyOf": [{"$ref": "#/$defs/TrendsFilter"}, {"type": "null"}], "default": null, "description": "Properties specific to the trends insight"}}, "required": ["series"], "title": "TrendsQuery", "type": "object"}'


class AssistantResponse(BaseModel):
    reasoning_steps: list[str]
    answer: TrendsQuery


class Assistant:
    _team: Team
    _system_prompt: str

    def __init__(self, team: Team):
        self._team = team
        self._system_prompt = self._prepare_system_prompt()

    def _replace_value_in_dict(self, item: Any, original_schema: Any):
        if isinstance(item, list):
            return [self._replace_value_in_dict(i, original_schema) for i in item]
        elif isinstance(item, dict):
            if list(item.keys()) == ["$ref"]:
                definitions = item["$ref"][2:].split("/")
                res = original_schema.copy()
                for definition in definitions:
                    res = res[definition]
                return res
            else:
                return {key: self._replace_value_in_dict(i, original_schema) for key, i in item.items()}
        else:
            return item

    @cached_property
    def _flat_schema(self):
        # schema = TrendsQuery.model_json_schema()
        schema = json.loads(hardcoded_schema)
        for _ in range(100):
            if "$ref" not in json.dumps(schema):
                break
            schema = self._replace_value_in_dict(schema.copy(), schema.copy())
        del schema["$defs"]
        return schema

    def _get_team_properties(self) -> str:
        available_properties = ""
        for property_type in PropertyDefinition.Type:
            if property_type in [PropertyDefinition.Type.GROUP, PropertyDefinition.Type.SESSION]:
                continue
            key_mapping = {
                PropertyDefinition.Type.EVENT: "event_properties",
            }

            props = (
                PropertyDefinition.objects.filter(team=self._team, type=property_type)
                .exclude(name__icontains="__")
                .exclude(name__icontains="phjs")
                .exclude(name__startswith="$survey_dismissed/")
                .exclude(name__startswith="$survey_responded/")
                .exclude(name__startswith="partial_filter_chosen_")
                .exclude(name__startswith="changed_action_")
                .exclude(name__icontains="window-id-")
                .exclude(name__startswith="changed_event_")
            )

            available_properties += f"\nBelow is the list of available {property_type.name.lower()} properties:\n"
            for prop in props:
                if prop.property_type is not None:
                    available_properties += f"{prop.name} ({prop.property_type})"
                    if property_type in key_mapping and prop.name in hardcoded_prop_defs[key_mapping[property_type]]:
                        data = hardcoded_prop_defs[key_mapping[property_type]][prop.name]
                        if "label" in data:
                            available_properties += f" - {data['label']}."
                        if "description" in data:
                            available_properties += f" {data['description']}".replace("\n", " ")
                        if "examples" in data:
                            available_properties += f" Examples: {data['examples']}."
                    available_properties += "\n"

        # Session hardcoded properties
        available_properties += "\nBelow is the list of available session properties:\n"
        for key, defs in hardcoded_prop_defs["session_properties"].items():
            available_properties += f"{key} ({defs['type']}) - {defs['label']}. {defs['description']}."
            if "examples" in defs:
                available_properties += f" Examples: {defs['examples']}."
            available_properties += "\n"

        return available_properties

    def _get_events(self) -> str:
        events = EventDefinition.objects.filter(team=self._team, last_seen_at__gte=timezone.now() - timedelta(days=180))

        event_description_mapping = {
            "$identify": "Identifies an anonymous user. This event doesn't show how many users you have but rather how many users used an account."
        }

        available_events = "Below is the list of available events:\n"
        for event in events:
            available_events += event.name
            if event.name in event_description_mapping:
                available_events += f" - {event_description_mapping[event.name]}"
            elif event.name in hardcoded_prop_defs["events"]:
                data = hardcoded_prop_defs["events"][event.name]
                available_events += f" - {data['label']}. {data['description']}".replace("\n", " ")
                if "examples" in data:
                    available_events += f" Examples: {data['examples']}."
            available_events += "\n"

        return available_events

    def _get_actions(self) -> str:
        actions = Action.objects.filter(team=self._team, deleted=False)
        available_actions = "Below is the list of available actions:\n"
        for action in actions:
            available_actions += f"{action.name} (ID: {action.id})\n"
        return available_actions

    def _prepare_system_prompt(self):
        return system_prompt.format(
            available_events=self._get_events(),
            available_properties=self._get_team_properties(),
            available_actions=self._get_actions(),
            trends_description=instructions_prompt,
        )

    def _json_schema_functions(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "output_insight_schema",
                    "description": "Outputs the JSON schema of a product analytics insight",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reasoning_steps": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "The reasoning steps leading to the final conclusion.",
                            },
                            "answer": self._flat_schema,
                        },
                    },
                },
            }
        ]

    def create_completion(self, messages: list[dict]):
        completions = openai.chat.completions.create(
            model="gpt-4o-2024-08-06",
            messages=[{"role": "system", "content": self._system_prompt}, *messages],
            tools=self._json_schema_functions(),
            tool_choice={"type": "function", "function": {"name": "output_insight_schema"}},
        )
        return AssistantResponse.model_validate_json(completions.choices[0].message.tool_calls[0].function.arguments)
