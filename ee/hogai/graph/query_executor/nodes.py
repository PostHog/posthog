from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    FailureMessage,
    FunnelVizType,
    VisualizationMessage,
)

from posthog.exceptions_capture import capture_exception

from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState

from ..base import AssistantNode
from .prompts import (
    FALLBACK_EXAMPLE_PROMPT,
    FUNNEL_STEPS_EXAMPLE_PROMPT,
    FUNNEL_TIME_TO_CONVERT_EXAMPLE_PROMPT,
    FUNNEL_TRENDS_EXAMPLE_PROMPT,
    QUERY_RESULTS_PROMPT,
    RETENTION_EXAMPLE_PROMPT,
    SQL_EXAMPLE_PROMPT,
    SQL_QUERY_PROMPT,
    TRENDS_EXAMPLE_PROMPT,
)
from .query_executor import AssistantQueryExecutor


class QueryExecutorNode(AssistantNode):
    name = AssistantNodeName.QUERY_EXECUTOR

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        viz_message = state.messages[-1]
        if isinstance(viz_message, FailureMessage):
            return PartialAssistantState()  # Exit early - something failed earlier
        if not isinstance(viz_message, VisualizationMessage):
            raise ValueError(f"Expected a visualization message, found {type(viz_message)}")
        if viz_message.answer is None:
            raise ValueError("Did not find query in the visualization message")

        tool_call_id = state.root_tool_call_id
        if not tool_call_id:
            return None

        query_runner = AssistantQueryExecutor(self._team, self._utc_now_datetime)
        try:
            results, used_fallback = query_runner.run_and_format_query(viz_message.answer)
            example_prompt = FALLBACK_EXAMPLE_PROMPT if used_fallback else self._get_example_prompt(viz_message)
        except Exception as err:
            if isinstance(err, NotImplementedError):
                raise
            capture_exception(err, additional_properties=self._get_debug_props(config))
            return PartialAssistantState(messages=[FailureMessage(content=str(err), id=str(uuid4()))])

        query_result = QUERY_RESULTS_PROMPT.format(
            query_kind=viz_message.answer.kind,
            results=results,
            utc_datetime_display=self.utc_now,
            project_datetime_display=self.project_now,
            project_timezone=self.project_timezone,
        )

        formatted_query_result = f"{example_prompt}\n\n{query_result}"
        if isinstance(viz_message.answer, AssistantHogQLQuery):
            formatted_query_result = f"{example_prompt}\n\n{SQL_QUERY_PROMPT.format(query=viz_message.answer.query)}\n\n{formatted_query_result}"

        partial_state = PartialAssistantState(
            messages=[
                AssistantToolCallMessage(content=formatted_query_result, id=str(uuid4()), tool_call_id=tool_call_id)
            ],
            root_tool_call_id=None,
            root_tool_insight_plan=None,
            root_tool_insight_type=None,
            rag_context=None,
        )

        # If create_dashboard_query is set, save the insight directly and store the ID
        if state.create_dashboard_query:
            from posthog.models import Insight

            # Save the insight immediately in the QueryExecutor (synchronous)
            # Truncate name and description to fit database constraints
            insight_name = (viz_message.query or "Dashboard Insight")[:400]  # Max 400 chars
            insight_description = (viz_message.plan or "Generated for dashboard")[:400]  # Max 400 chars

            # Convert the AI-generated query to proper filters for better display
            # This ensures insights show up as trends, funnels, etc. instead of custom insights
            filters = {}
            query = None

            if hasattr(viz_message.answer, "kind"):
                # Map the query kind to insight type
                kind_to_insight_type = {
                    "TrendsQuery": "TRENDS",
                    "FunnelsQuery": "FUNNELS",
                    "RetentionQuery": "RETENTION",
                    "PathsQuery": "PATHS",
                    "StickinessQuery": "STICKINESS",
                    "LifecycleQuery": "LIFECYCLE",
                }

                insight_type = kind_to_insight_type.get(viz_message.answer.kind)
                if insight_type:
                    # Set the insight type in filters so it displays properly
                    filters["insight"] = insight_type

                    # Convert the query structure to filters format
                    answer_dict = viz_message.answer.model_dump(mode="json", exclude_none=True)

                    # Convert series to events/actions
                    if answer_dict.get("series"):
                        events = []
                        actions = []
                        data_warehouse = []

                        for i, series_item in enumerate(answer_dict["series"]):
                            entity = {
                                "type": "events"
                                if series_item.get("kind") == "EventsNode"
                                else "actions"
                                if series_item.get("kind") == "ActionsNode"
                                else "data_warehouse",
                                "id": series_item.get("event")
                                or series_item.get("id")
                                or series_item.get("table_name"),
                                "order": i,
                                "name": series_item.get("name"),
                                "custom_name": series_item.get("custom_name"),
                                "math": series_item.get("math"),
                                "math_property": series_item.get("math_property"),
                                "math_property_type": series_item.get("math_property_type"),
                                "math_hogql": series_item.get("math_hogql"),
                                "math_group_type_index": series_item.get("math_group_type_index"),
                                "properties": series_item.get("properties"),
                            }

                            if series_item.get("kind") == "EventsNode":
                                events.append(entity)
                            elif series_item.get("kind") == "ActionsNode":
                                actions.append(entity)
                            elif series_item.get("kind") == "DataWarehouseNode":
                                entity.update(
                                    {
                                        "table_name": series_item.get("table_name"),
                                        "id_field": series_item.get("id_field"),
                                        "timestamp_field": series_item.get("timestamp_field"),
                                        "distinct_id_field": series_item.get("distinct_id_field"),
                                    }
                                )
                                data_warehouse.append(entity)

                        if events:
                            filters["events"] = events
                        if actions:
                            filters["actions"] = actions
                        if data_warehouse:
                            filters["data_warehouse"] = data_warehouse

                    # Convert date range
                    if answer_dict.get("dateRange"):
                        date_range = answer_dict["dateRange"]
                        if "date_from" in date_range:
                            filters["date_from"] = date_range["date_from"]
                        if "date_to" in date_range:
                            filters["date_to"] = date_range["date_to"]
                        if "explicitDate" in date_range:
                            filters["explicit_date"] = date_range["explicitDate"]

                    # Convert interval
                    if "interval" in answer_dict:
                        filters["interval"] = answer_dict["interval"]

                    # Convert properties
                    if answer_dict.get("properties"):
                        filters["properties"] = answer_dict["properties"]

                    # Convert filter test accounts
                    if "filterTestAccounts" in answer_dict:
                        filters["filter_test_accounts"] = answer_dict["filterTestAccounts"]

                    # Convert sampling factor
                    if "samplingFactor" in answer_dict:
                        filters["sampling_factor"] = answer_dict["samplingFactor"]

                    # Convert breakdown filter
                    if answer_dict.get("breakdownFilter"):
                        breakdown = answer_dict["breakdownFilter"]
                        if "breakdown" in breakdown:
                            filters["breakdown"] = breakdown["breakdown"]
                        if "breakdown_type" in breakdown:
                            filters["breakdown_type"] = breakdown["breakdown_type"]
                        if "breakdown_normalize_url" in breakdown:
                            filters["breakdown_normalize_url"] = breakdown["breakdown_normalize_url"]
                        if "breakdowns" in breakdown:
                            filters["breakdowns"] = breakdown["breakdowns"]
                        if "breakdown_group_type_index" in breakdown:
                            filters["breakdown_group_type_index"] = breakdown["breakdown_group_type_index"]
                        if "breakdown_hide_other_aggregation" in breakdown:
                            filters["breakdown_hide_other_aggregation"] = breakdown["breakdown_hide_other_aggregation"]
                        if "breakdown_limit" in breakdown:
                            filters["breakdown_limit"] = breakdown["breakdown_limit"]

                    # Convert compare filter
                    if answer_dict.get("compareFilter"):
                        compare = answer_dict["compareFilter"]
                        if "compare" in compare:
                            filters["compare"] = compare["compare"]
                        if "compare_to" in compare:
                            filters["compare_to"] = compare["compare_to"]

                    # Convert specific filter types
                    if insight_type == "TRENDS" and "trendsFilter" in answer_dict:
                        trends_filter = answer_dict["trendsFilter"]
                        if "display" in trends_filter:
                            filters["display"] = trends_filter["display"]
                        if "show_values_on_series" in trends_filter:
                            filters["show_values_on_series"] = trends_filter["show_values_on_series"]
                        if "show_percent_stack_view" in trends_filter:
                            filters["show_percent_stack_view"] = trends_filter["show_percent_stack_view"]
                        if "show_legend" in trends_filter:
                            filters["show_legend"] = trends_filter["show_legend"]
                        if "aggregation_axis_format" in trends_filter:
                            filters["aggregation_axis_format"] = trends_filter["aggregation_axis_format"]
                        if "aggregation_axis_prefix" in trends_filter:
                            filters["aggregation_axis_prefix"] = trends_filter["aggregation_axis_prefix"]
                        if "aggregation_axis_suffix" in trends_filter:
                            filters["aggregation_axis_suffix"] = trends_filter["aggregation_axis_suffix"]
                        if "formula" in trends_filter:
                            filters["formula"] = trends_filter["formula"]
                        if "hidden_legend_indexes" in trends_filter:
                            filters["hidden_legend_indexes"] = trends_filter["hidden_legend_indexes"]
                        if "smoothing_intervals" in trends_filter:
                            filters["smoothing_intervals"] = trends_filter["smoothing_intervals"]
                        if "trends_math" in trends_filter:
                            filters["trends_math"] = trends_filter["trends_math"]
                        if "show_labels_on_series" in trends_filter:
                            filters["show_labels_on_series"] = trends_filter["show_labels_on_series"]
                        if "show_aggregated_value" in trends_filter:
                            filters["show_aggregated_value"] = trends_filter["show_aggregated_value"]

                    elif insight_type == "FUNNELS" and "funnelsFilter" in answer_dict:
                        funnels_filter = answer_dict["funnelsFilter"]
                        if "funnel_viz_type" in funnels_filter:
                            filters["funnel_viz_type"] = funnels_filter["funnel_viz_type"]
                        if "funnel_order_type" in funnels_filter:
                            filters["funnel_order_type"] = funnels_filter["funnel_order_type"]
                        if "exclusions" in funnels_filter:
                            filters["exclusions"] = funnels_filter["exclusions"]
                        if "bin_count" in funnels_filter:
                            filters["bin_count"] = funnels_filter["bin_count"]
                        if "funnel_window_interval" in funnels_filter:
                            filters["funnel_window_interval"] = funnels_filter["funnel_window_interval"]
                        if "funnel_window_interval_unit" in funnels_filter:
                            filters["funnel_window_interval_unit"] = funnels_filter["funnel_window_interval_unit"]
                        if "funnel_from_step" in funnels_filter:
                            filters["funnel_from_step"] = funnels_filter["funnel_from_step"]
                        if "funnel_to_step" in funnels_filter:
                            filters["funnel_to_step"] = funnels_filter["funnel_to_step"]
                        if "funnel_step_reference" in funnels_filter:
                            filters["funnel_step_reference"] = funnels_filter["funnel_step_reference"]
                        if "entrance_period_start" in funnels_filter:
                            filters["entrance_period_start"] = funnels_filter["entrance_period_start"]
                        if "drop_off" in funnels_filter:
                            filters["drop_off"] = funnels_filter["drop_off"]
                        if "hidden_legend_keys" in funnels_filter:
                            filters["hidden_legend_keys"] = funnels_filter["hidden_legend_keys"]
                        if "show_values_on_series" in funnels_filter:
                            filters["show_values_on_series"] = funnels_filter["show_values_on_series"]
                        if "show_legend" in funnels_filter:
                            filters["show_legend"] = funnels_filter["show_legend"]
                        if "aggregation_group_type_index" in funnels_filter:
                            filters["aggregation_group_type_index"] = funnels_filter["aggregation_group_type_index"]

                    elif insight_type == "RETENTION" and "retentionFilter" in answer_dict:
                        retention_filter = answer_dict["retentionFilter"]
                        if "retention_type" in retention_filter:
                            filters["retention_type"] = retention_filter["retention_type"]
                        if "target_entity" in retention_filter:
                            filters["target_entity"] = retention_filter["target_entity"]
                        if "returning_entity" in retention_filter:
                            filters["returning_entity"] = retention_filter["returning_entity"]
                        if "period" in retention_filter:
                            filters["period"] = retention_filter["period"]
                        if "total_intervals" in retention_filter:
                            filters["total_intervals"] = retention_filter["total_intervals"]
                        if "retention_reference" in retention_filter:
                            filters["retention_reference"] = retention_filter["retention_reference"]
                        if "aggregation_group_type_index" in retention_filter:
                            filters["aggregation_group_type_index"] = retention_filter["aggregation_group_type_index"]

                    elif insight_type == "PATHS" and "pathsFilter" in answer_dict:
                        paths_filter = answer_dict["pathsFilter"]
                        if "path_type" in paths_filter:
                            filters["path_type"] = paths_filter["path_type"]
                        if "start_point" in paths_filter:
                            filters["start_point"] = paths_filter["start_point"]
                        if "end_point" in paths_filter:
                            filters["end_point"] = paths_filter["end_point"]
                        if "include_custom_events" in paths_filter:
                            filters["include_custom_events"] = paths_filter["include_custom_events"]
                        if "include_pageviews" in paths_filter:
                            filters["include_pageviews"] = paths_filter["include_pageviews"]
                        if "include_autocapture" in paths_filter:
                            filters["include_autocapture"] = paths_filter["include_autocapture"]
                        if "exclude_events" in paths_filter:
                            filters["exclude_events"] = paths_filter["exclude_events"]
                        if "step_limit" in paths_filter:
                            filters["step_limit"] = paths_filter["step_limit"]
                        if "min_edge_weight" in paths_filter:
                            filters["min_edge_weight"] = paths_filter["min_edge_weight"]
                        if "max_edge_weight" in paths_filter:
                            filters["max_edge_weight"] = paths_filter["max_edge_weight"]
                        if "edge_limit" in paths_filter:
                            filters["edge_limit"] = paths_filter["edge_limit"]
                        if "funnel_paths" in paths_filter:
                            filters["funnel_paths"] = paths_filter["funnel_paths"]
                        if "local_path_cleaning_filters" in paths_filter:
                            filters["local_path_cleaning_filters"] = paths_filter["local_path_cleaning_filters"]
                        if "path_replacements" in paths_filter:
                            filters["path_replacements"] = paths_filter["path_replacements"]
                        if "aggregation_group_type_index" in paths_filter:
                            filters["aggregation_group_type_index"] = paths_filter["aggregation_group_type_index"]

                    elif insight_type == "STICKINESS" and "stickinessFilter" in answer_dict:
                        stickiness_filter = answer_dict["stickinessFilter"]
                        if "show_legend" in stickiness_filter:
                            filters["show_legend"] = stickiness_filter["show_legend"]
                        if "show_values_on_series" in stickiness_filter:
                            filters["show_values_on_series"] = stickiness_filter["show_values_on_series"]
                        if "hidden_legend_indexes" in stickiness_filter:
                            filters["hidden_legend_indexes"] = stickiness_filter["hidden_legend_indexes"]
                        if "aggregation_group_type_index" in stickiness_filter:
                            filters["aggregation_group_type_index"] = stickiness_filter["aggregation_group_type_index"]

                    elif insight_type == "LIFECYCLE" and "lifecycleFilter" in answer_dict:
                        lifecycle_filter = answer_dict["lifecycleFilter"]
                        if "show_values_on_series" in lifecycle_filter:
                            filters["show_values_on_series"] = lifecycle_filter["show_values_on_series"]
                        if "show_legend" in lifecycle_filter:
                            filters["show_legend"] = lifecycle_filter["show_legend"]
                        if "toggled_lifecycles" in lifecycle_filter:
                            filters["toggled_lifecycles"] = lifecycle_filter["toggled_lifecycles"]
                        if "aggregation_group_type_index" in lifecycle_filter:
                            filters["aggregation_group_type_index"] = lifecycle_filter["aggregation_group_type_index"]

                    # Store the query as None so it uses the legacy filters system
                    query = None
                else:
                    # Fallback to storing as custom insight if we can't determine type
                    query = viz_message.answer.model_dump(mode="json", exclude_none=True)
            else:
                # Fallback to storing as custom insight
                query = viz_message.answer.model_dump(mode="json", exclude_none=True)

            insight = Insight.objects.create(
                name=insight_name,
                team=self._team,
                created_by=self._user,
                query=query,
                filters=filters,
                description=insight_description,
            )

            partial_state.insight_ids = [insight.id]

        return partial_state

    def _get_example_prompt(self, viz_message: VisualizationMessage) -> str:
        if isinstance(viz_message.answer, AssistantTrendsQuery):
            return TRENDS_EXAMPLE_PROMPT
        if isinstance(viz_message.answer, AssistantFunnelsQuery):
            if (
                not viz_message.answer.funnelsFilter
                or not viz_message.answer.funnelsFilter.funnelVizType
                or viz_message.answer.funnelsFilter.funnelVizType == FunnelVizType.STEPS
            ):
                return FUNNEL_STEPS_EXAMPLE_PROMPT
            if viz_message.answer.funnelsFilter.funnelVizType == FunnelVizType.TIME_TO_CONVERT:
                return FUNNEL_TIME_TO_CONVERT_EXAMPLE_PROMPT
            return FUNNEL_TRENDS_EXAMPLE_PROMPT
        if isinstance(viz_message.answer, AssistantRetentionQuery):
            return RETENTION_EXAMPLE_PROMPT
        if isinstance(viz_message.answer, AssistantHogQLQuery):
            return SQL_EXAMPLE_PROMPT
        raise NotImplementedError(f"Unsupported query type: {type(viz_message.answer)}")
