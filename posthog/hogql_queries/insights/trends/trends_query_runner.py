import threading
from copy import deepcopy
from datetime import datetime, timedelta
from math import ceil
from operator import itemgetter
from typing import Any, Optional, Union

from django.conf import settings
from django.db import models
from django.db.models.functions import Coalesce

from natsort import natsorted, ns

from posthog.schema import (
    ActionsNode,
    BreakdownItem,
    BreakdownType,
    CachedTrendsQueryResponse,
    ChartDisplayType,
    Compare,
    CompareItem,
    DashboardFilter,
    DataWarehouseEventsModifier,
    DataWarehouseNode,
    DayItem,
    EventsNode,
    HogQLQueryModifiers,
    HogQLQueryResponse,
    InCohortVia,
    InsightActorsQueryOptionsResponse,
    IntervalType,
    MultipleBreakdownOptions,
    MultipleBreakdownType,
    QueryTiming,
    ResolvedDateRangeResponse,
    Series,
    TrendsFormulaNode,
    TrendsQuery,
    TrendsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, LimitContext
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings

from posthog.caching.insights_api import (
    BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL,
    REAL_TIME_INSIGHT_REFRESH_INTERVAL,
    REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL,
)
from posthog.clickhouse import query_tagging
from posthog.clickhouse.query_tagging import QueryTags
from posthog.hogql_queries.insights.trends.breakdown import (
    BREAKDOWN_NULL_DISPLAY,
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_NUMERIC_ALL_VALUES_PLACEHOLDER,
    BREAKDOWN_OTHER_DISPLAY,
    BREAKDOWN_OTHER_STRING_LABEL,
)
from posthog.hogql_queries.insights.trends.display import TrendsDisplay
from posthog.hogql_queries.insights.trends.series_with_extras import SeriesWithExtras
from posthog.hogql_queries.insights.trends.trends_actors_query_builder import TrendsActorsQueryBuilder
from posthog.hogql_queries.insights.trends.trends_query_builder import TrendsQueryBuilder
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.formula_ast import FormulaAST
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.hogql_queries.utils.timestamp_utils import format_label_date, get_earliest_timestamp_from_series
from posthog.models import Team
from posthog.models.action.action import Action
from posthog.models.cohort.cohort import Cohort
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property_definition import PropertyDefinition
from posthog.queries.util import correct_result_for_sampling
from posthog.utils import multisort

from products.data_warehouse.backend.models.util import get_view_or_table_by_name


class TrendsQueryRunner(AnalyticsQueryRunner[TrendsQueryResponse]):
    query: TrendsQuery
    cached_response: CachedTrendsQueryResponse
    series: list[SeriesWithExtras]

    def __init__(
        self,
        query: TrendsQuery | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        from posthog.hogql_queries.insights.utils.utils import convert_active_user_math_based_on_interval

        if isinstance(query, dict):
            query = TrendsQuery.model_validate(query)

        assert isinstance(query, TrendsQuery)

        # For backwards compatibility
        if query.trendsFilter:
            if not query.trendsFilter.formulaNodes:
                if query.trendsFilter.formulas:
                    query.trendsFilter.formulaNodes = [
                        TrendsFormulaNode(formula=formula) for formula in query.trendsFilter.formulas
                    ]
                elif query.trendsFilter.formula:
                    query.trendsFilter.formulaNodes = [TrendsFormulaNode(formula=query.trendsFilter.formula)]
            query.trendsFilter.formula = None
            query.trendsFilter.formulas = None

        # Use the new function to handle WAU/MAU conversions
        query = convert_active_user_math_based_on_interval(query)

        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

    def __post_init__(self):
        self.update_hogql_modifiers()
        self.series = self.setup_series()

    def _refresh_frequency(self):
        date_to = self.query_date_range.date_to()
        date_from = self.query_date_range.date_from()
        interval = self.query_date_range.interval_name

        delta_days: Optional[int] = None
        if date_from and date_to:
            delta = date_to - date_from
            delta_days = ceil(delta.total_seconds() / timedelta(days=1).total_seconds())

        if interval == "minute":
            return REAL_TIME_INSIGHT_REFRESH_INTERVAL

        if interval == "hour" or (delta_days is not None and delta_days <= 7):
            # The interval is shorter for short-term insights
            return REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL

        return BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return ast.SelectSetQuery.create_from_queries(self.to_queries(), "UNION ALL")

    def to_queries(self) -> list[ast.SelectQuery | ast.SelectSetQuery]:
        queries = []
        with self.timings.measure("trends_to_query"):
            earliest_timestamp = self._earliest_timestamp
            for series in self.series:
                if not series.is_previous_period_series:
                    query_date_range = self.query_date_range
                else:
                    query_date_range = self.query_previous_date_range

                query_date_range._earliest_timestamp_fallback = earliest_timestamp

                query_builder = TrendsQueryBuilder(
                    trends_query=series.overriden_query or self.query,
                    team=self.team,
                    query_date_range=query_date_range,
                    series=series.series,
                    timings=self.timings,
                    modifiers=self.modifiers,
                    limit_context=self.limit_context,
                )
                query = query_builder.build_query()

                # Get around the default 100 limit, bump to the max 10000.
                # This is useful for the world map view and other cases with a lot of breakdowns.
                if isinstance(query, ast.SelectQuery) and query.limit is None:
                    query.limit = ast.Constant(value=MAX_SELECT_RETURNED_ROWS)
                queries.append(query)

        return queries

    def to_events_query(self, *args, **kwargs) -> ast.SelectQuery:
        with self.timings.measure("trends_to_events_query"):
            query_builder = self._get_trends_actors_query_builder(*args, **kwargs)
            query = query_builder._get_events_query()

        return query

    def to_actors_query(self, *args, **kwargs) -> ast.SelectQuery:
        with self.timings.measure("trends_to_actors_query"):
            query_builder = self._get_trends_actors_query_builder(*args, **kwargs)
            query = query_builder.build_actors_query()

        return query

    def _get_trends_actors_query_builder(
        self,
        time_frame: Optional[str],
        series_index: int,
        breakdown_value: Optional[str | int | list[str]] = None,
        compare_value: Optional[Compare] = None,
        include_recordings: Optional[bool] = None,
    ) -> TrendsActorsQueryBuilder:
        if self.query.breakdownFilter and self.query.breakdownFilter.breakdown_type == BreakdownType.COHORT:
            if self.query.breakdownFilter.breakdown in ("all", ["all"]) or breakdown_value == "all":
                self.query.breakdownFilter = None
            elif isinstance(self.query.breakdownFilter.breakdown, list):
                self.query.breakdownFilter.breakdown = [x for x in self.query.breakdownFilter.breakdown if x != "all"]
        query_builder = TrendsActorsQueryBuilder(
            trends_query=self.query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            # actors related args
            time_frame=time_frame,
            series_index=series_index,
            breakdown_value=breakdown_value if breakdown_value != "all" else None,
            compare_value=compare_value,
            include_recordings=include_recordings,
        )

        return query_builder

    def to_actors_query_options(self) -> InsightActorsQueryOptionsResponse:
        res_breakdown: list[BreakdownItem] | None = None
        res_breakdowns: list[MultipleBreakdownOptions] | None = None

        res_series: list[Series] = []
        res_compare: list[CompareItem] | None = None

        # Days
        res_days: Optional[list[DayItem]] = (
            None
            if self._trends_display.is_total_value()
            else [
                DayItem(
                    label=format_label_date(value, self.query_date_range, self.team.week_start_day),
                    value=value,
                )
                for value in self.query_date_range.all_values()
            ]
        )

        # Series
        for index, series in enumerate(self.query.series):
            series_label = self.series_event(series)
            res_series.append(Series(label="All events" if series_label is None else series_label, value=index))

        # Compare
        if self.query.compareFilter is not None and self.query.compareFilter.compare:
            res_compare = [
                CompareItem(label="Current", value="current"),
                CompareItem(label="Previous", value="previous"),
            ]

        # Breakdowns
        if self.query.breakdownFilter is not None and (
            self.query.breakdownFilter.breakdown is not None
            or (self.query.breakdownFilter.breakdowns is not None and len(self.query.breakdownFilter.breakdowns) > 0)
        ):
            if self.query.breakdownFilter.breakdown_type == "cohort":
                assert isinstance(self.query.breakdownFilter.breakdown, list)

                res_breakdown = []
                for value in self.query.breakdownFilter.breakdown:
                    if value != "all" and str(value) != "0":
                        res_breakdown.append(
                            BreakdownItem(
                                label=Cohort.objects.get(pk=int(value), team__project_id=self.team.project_id).name,
                                value=value,
                            )
                        )
                    else:
                        res_breakdown.append(BreakdownItem(label="all users", value="all"))
            else:
                # TODO: Work out if we will have issues only getting breakdown values for
                # the "current" period and not "previous" period for when "compare" is turned on
                query_date_range = self.query_date_range

                query_builder = TrendsQueryBuilder(
                    trends_query=self.query,
                    team=self.team,
                    query_date_range=query_date_range,
                    series=series,
                    timings=self.timings,
                    modifiers=self.modifiers,
                    limit_context=self.limit_context,
                )

                query = query_builder.build_query()
                breakdown = query_builder.breakdown

                results = execute_hogql_query(
                    query_type="TrendsActorsQueryOptions",
                    query=query,
                    team=self.team,
                    # timings=timings,
                    # modifiers=modifiers,
                )

                breakdown_values = [
                    row[results.columns.index("breakdown_value") if results.columns else 2] for row in results.results
                ]

                if breakdown.is_multiple_breakdown:
                    assert self.query.breakdownFilter.breakdowns is not None  # type checking

                    res_breakdowns = []

                    for breakdown_filter, zipped_values in zip(
                        self.query.breakdownFilter.breakdowns, zip(*breakdown_values)
                    ):
                        values: list[str] = list(zipped_values)
                        res_breakdowns.append(
                            MultipleBreakdownOptions(
                                values=self._get_breakdown_items(
                                    values,
                                    breakdown_filter.property,
                                    breakdown_filter.type,
                                    histogram_breakdown=isinstance(breakdown_filter.histogram_bin_count, int),
                                    group_type_index=breakdown_filter.group_type_index,
                                )
                            )
                        )
                elif self.query.breakdownFilter.breakdown is not None:
                    res_breakdown = self._get_breakdown_items(
                        breakdown_values,
                        self.query.breakdownFilter.breakdown,
                        self.query.breakdownFilter.breakdown_type,
                        histogram_breakdown=isinstance(self.query.breakdownFilter.breakdown_histogram_bin_count, int),
                        group_type_index=self.query.breakdownFilter.breakdown_group_type_index,
                        is_boolean_field=self._is_breakdown_filter_field_boolean(),
                    )

        return InsightActorsQueryOptionsResponse(
            series=res_series,
            breakdown=res_breakdown,
            breakdowns=res_breakdowns,
            day=res_days,
            compare=res_compare,
        )

    def _calculate(self):
        queries = self.to_queries()

        if len(queries) == 0:
            response_hogql = ""
        else:
            if len(queries) == 1:
                response_hogql_query = queries[0]
            else:
                response_hogql_query = ast.SelectSetQuery.create_from_queries(queries, "UNION ALL")

            with self.timings.measure("printing_hogql_for_response"):
                response_hogql = to_printed_hogql(response_hogql_query, self.team, self.modifiers)

        res_matrix: list[list[Any] | Any | None] = [None] * len(queries)
        timings_matrix: list[list[QueryTiming] | None] = [None] * (2 + len(queries))
        errors: list[Exception] = []
        debug_errors: list[str] = []

        def run(
            index: int,
            query: ast.SelectQuery | ast.SelectSetQuery,
            timings: HogQLTimings,
            is_parallel: bool,
            query_tags: Optional[QueryTags] = None,
        ):
            try:
                if query_tags:
                    query_tagging.update_tags(query_tags)

                series_with_extra = self.series[index]

                response = execute_hogql_query(
                    query_type="TrendsQuery",
                    query=query,
                    team=self.team,
                    timings=timings,
                    modifiers=self.modifiers,
                    limit_context=self.limit_context,
                )

                timings_matrix[index + 1] = response.timings
                res_matrix[index] = self.build_series_response(response, series_with_extra, len(queries))
                if response.error:
                    debug_errors.append(response.error)
            except Exception as e:
                errors.append(e)
            finally:
                if is_parallel:
                    from django.db import connection

                    # This will only close the DB connection for the newly spawned thread and not the whole app
                    connection.close()

        with self.timings.measure("execute_queries"):
            timings_matrix[0] = self.timings.to_list(back_out_stack=False)
            self.timings.clear_timings()

            # This exists so that we're not spawning threads during unit tests. We can't do
            # this right now due to the lack of multithreaded support of Django
            if len(queries) == 1 or settings.IN_UNIT_TESTING:
                for index, query in enumerate(queries):
                    run(index, query, self.timings.clone_for_subquery(index), False)
            else:
                jobs = [
                    threading.Thread(
                        target=run,
                        args=(
                            index,
                            query,
                            self.timings.clone_for_subquery(index),
                            True,
                            query_tagging.get_query_tags().model_copy(deep=True),
                        ),
                    )
                    for index, query in enumerate(queries)
                ]
                [j.start() for j in jobs]  # type:ignore
                [j.join() for j in jobs]  # type:ignore

        # Raise any errors raised in a seperate thread
        if len(errors) > 0:
            raise errors[0]

        # Flatten res and timings
        returned_results: list[list[dict[str, Any]]] = []
        for result in res_matrix:
            if isinstance(result, list):
                returned_results.append(result)
            elif isinstance(result, dict):
                returned_results.append([result])

        final_result: list[dict] = []
        formula_nodes = self.query.trendsFilter and self.query.trendsFilter.formulaNodes

        if formula_nodes:
            with self.timings.measure("apply_formula"):
                has_compare = bool(self.query.compareFilter and self.query.compareFilter.compare)
                if has_compare:
                    current_results = returned_results[: len(returned_results) // 2]
                    previous_results = returned_results[len(returned_results) // 2 :]

                    final_result = []
                    for formula_idx, formula_node in enumerate(formula_nodes):
                        current_formula_results = self.apply_formula(formula_node, current_results)
                        previous_formula_results = self.apply_formula(formula_node, previous_results)
                        # Create a new list for each formula's results
                        formula_results = []
                        formula_results.extend(current_formula_results)
                        formula_results.extend(previous_formula_results)

                        # Set the order based on the formula index
                        for result in formula_results:
                            result["order"] = formula_idx

                        final_result.extend(formula_results)
                else:
                    for formula_idx, formula_node in enumerate(formula_nodes):
                        formula_results = self.apply_formula(formula_node, returned_results)

                        # Set the order based on the formula index
                        for result in formula_results:
                            result["order"] = formula_idx

                        # Create a new list for each formula's results
                        final_result.extend(formula_results)
        else:
            for result in returned_results:
                if isinstance(result, list):
                    for item in result:
                        # Set the order for each item based on the action order
                        item["order"] = item.get("action", {}).get("order", 0)

                    final_result.extend(result)
                elif isinstance(result, dict):  # type: ignore [unreachable]
                    raise ValueError("This should not happen")

        timings_matrix[-1] = self.timings.to_list()

        timings: list[QueryTiming] = []
        for timing in timings_matrix:
            if isinstance(timing, list):
                timings.extend(timing)

        has_more = False
        if self.breakdown_enabled and any(self._is_other_breakdown(item["breakdown_value"]) for item in final_result):
            if self.query.breakdownFilter and self.query.breakdownFilter.breakdown_hide_other_aggregation:
                final_result = [item for item in final_result if not self._is_other_breakdown(item["breakdown_value"])]
            has_more = True

        return TrendsQueryResponse(
            results=final_result,
            hasMore=has_more,
            timings=timings,
            hogql=response_hogql,
            modifiers=self.modifiers,
            error=". ".join(debug_errors),
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )

    def build_series_response(self, response: HogQLQueryResponse, series: SeriesWithExtras, series_count: int):
        def get_value(name: str, val: Any):
            if name not in ["date", "total", "breakdown_value"]:
                raise Exception("Column not found in hogql results")
            if response.columns is None:
                raise Exception("No columns returned from hogql results")
            if name not in response.columns:
                return None
            index = response.columns.index(name)
            return val[index]

        real_series_count = series_count
        if self.query.compareFilter is not None and self.query.compareFilter.compare:
            real_series_count = ceil(series_count / 2)

        res = []
        for val in response.results:
            try:
                series_label = self.series_event(series.series)
            except Action.DoesNotExist:
                # Dont append the series if the action doesnt exist
                continue

            if series.aggregate_values:
                series_object = {
                    "data": [],
                    "days": (
                        [
                            item.strftime(
                                "%Y-%m-%d{}".format(
                                    " %H:%M:%S" if self.query_date_range.interval_name in ("hour", "minute") else ""
                                )
                            )
                            for item in get_value("date", val)
                        ]
                        if response.columns and "date" in response.columns
                        else []
                    ),
                    "count": 0,
                    "aggregated_value": get_value("total", val),
                    "label": "All events" if series_label is None else series_label,
                    "filter": self._query_to_filter(),
                    "action": {  # TODO: Populate missing props in `action`
                        "days": self.query_date_range.all_values(),
                        "id": series_label,
                        "type": "events",
                        "order": series.series_order,
                        "name": series_label or "All events",
                        "custom_name": series.series.custom_name,
                        "math": series.series.math,
                        "math_property": series.series.math_property,
                        "math_hogql": series.series.math_hogql,
                        "math_group_type_index": series.series.math_group_type_index,
                        "properties": {},
                    },
                }
            else:
                if self._trends_display.display_type == ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE:
                    count = get_value("total", val)[-1]
                else:
                    count = float(sum(get_value("total", val)))

                series_object = {
                    "data": get_value("total", val),
                    "labels": [
                        format_label_date(item, self.query_date_range, self.team.week_start_day)
                        for item in get_value("date", val)
                    ],
                    "days": [
                        item.strftime(
                            "%Y-%m-%d{}".format(
                                " %H:%M:%S" if self.query_date_range.interval_name in ("hour", "minute") else ""
                            )
                        )
                        for item in get_value("date", val)
                    ],
                    "count": count,
                    "label": "All events" if series_label is None else series_label,
                    "filter": self._query_to_filter(),
                    "action": {  # TODO: Populate missing props in `action`
                        "days": self.query_date_range.all_values(),
                        "id": series_label,
                        "type": "events",
                        "order": series.series_order,
                        "name": series_label or "All events",
                        "custom_name": series.series.custom_name,
                        "math": series.series.math,
                        "math_property": series.series.math_property,
                        "math_hogql": series.series.math_hogql,
                        "math_group_type_index": series.series.math_group_type_index,
                        "properties": {},
                    },
                }

            # Modifications for when comparing to previous period
            if self.query.compareFilter is not None and self.query.compareFilter.compare:
                series_object["compare"] = True
                series_object["compare_label"] = "previous" if series.is_previous_period_series else "current"

            # Modifications for when breakdowns are active
            if self.breakdown_enabled:
                assert self.query.breakdownFilter is not None  # type checking

                remapped_label = None

                if self._is_breakdown_filter_field_boolean():
                    remapped_label = self._convert_boolean(get_value("breakdown_value", val))

                    if remapped_label == "" or remapped_label is None:
                        # Skip the "none" series if it doesn't have any data
                        if series_object["count"] == 0 and series_object.get("aggregated_value", 0) == 0:
                            continue
                        remapped_label = "none"

                    # if count of series == 1, then we don't need to include the object label in the series label
                    if real_series_count > 1:
                        series_object["label"] = "{} - {}".format(series_object["label"], remapped_label)
                    else:
                        series_object["label"] = remapped_label
                    series_object["breakdown_value"] = remapped_label
                elif self.query.breakdownFilter.breakdown_type == "cohort":
                    cohort_id = get_value("breakdown_value", val)
                    cohort_name = "all users" if str(cohort_id) == "0" else Cohort.objects.get(pk=cohort_id).name

                    if real_series_count > 1:
                        series_object["label"] = "{} - {}".format(series_object["label"], cohort_name)
                    else:
                        series_object["label"] = cohort_name
                    series_object["breakdown_value"] = "all" if str(cohort_id) == "0" else int(cohort_id)
                else:
                    remapped_label = get_value("breakdown_value", val)
                    if remapped_label == "" or remapped_label is None:
                        # Skip the "none" series if it doesn't have any data
                        if series_object["count"] == 0 and series_object.get("aggregated_value", 0) == 0:
                            continue
                        remapped_label = "none"

                    formatted_breakdown_value = self._format_breakdown_label(remapped_label)

                    # If there's multiple series, include the object label in the series label
                    if real_series_count > 1:
                        series_object["label"] = "{} - {}".format(series_object["label"], formatted_breakdown_value)
                    else:
                        series_object["label"] = formatted_breakdown_value

                    series_object["breakdown_value"] = remapped_label

            if self.query.samplingFactor and self.query.samplingFactor != 1:
                factor = self.query.samplingFactor
                math = series_object.get("action", {}).get("math")
                if "count" in series_object:
                    series_object["count"] = correct_result_for_sampling(series_object["count"], factor, math)
                if "aggregated_value" in series_object:
                    series_object["aggregated_value"] = correct_result_for_sampling(
                        series_object["aggregated_value"], factor, math
                    )
                if "data" in series_object:
                    series_object["data"] = [
                        correct_result_for_sampling(value, factor, math) for value in series_object["data"]
                    ]

            res.append(series_object)
        return res

    @property
    def exact_timerange(self):
        return self.query.trendsFilter and self.query.trendsFilter.display == ChartDisplayType.BOLD_NUMBER

    @cached_property
    def _earliest_timestamp(self) -> datetime | None:
        if self.query.dateRange and self.query.dateRange.date_from == "all":
            # Get earliest timestamp across all series in this insight
            return get_earliest_timestamp_from_series(team=self.team, series=[series.series for series in self.series])

        return None

    @cached_property
    def query_date_range(self):
        interval = IntervalType.DAY if self._trends_display.is_total_value() else self.query.interval

        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=interval,
            now=datetime.now(),
            exact_timerange=self.exact_timerange,
        )

    @cached_property
    def query_previous_date_range(self):
        # We set exact_timerange here because we want to compare to the previous period that has happened up to this exact time
        if self.query.compareFilter is not None and isinstance(self.query.compareFilter.compare_to, str):
            return QueryCompareToDateRange(
                date_range=self.query.dateRange,
                team=self.team,
                interval=self.query.interval,
                now=datetime.now(),
                compare_to=self.query.compareFilter.compare_to,
                exact_timerange=self.exact_timerange,
            )
        return QueryPreviousPeriodDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval,
            now=datetime.now(),
            exact_timerange=self.exact_timerange,
        )

    def series_event(self, series: Union[EventsNode, ActionsNode, DataWarehouseNode]) -> str | None:
        if isinstance(series, EventsNode):
            return series.event
        if isinstance(series, ActionsNode):
            # TODO: Can we load the Action in more efficiently?
            action = Action.objects.get(pk=int(series.id), team__project_id=self.team.project_id)
            return action.name

        if isinstance(series, DataWarehouseNode):
            return series.table_name

        return None  # type: ignore [unreachable]

    def update_hogql_modifiers(self) -> None:
        if (
            self.modifiers.inCohortVia == InCohortVia.AUTO
            and self.query.breakdownFilter is not None
            and self.query.breakdownFilter.breakdown_type == "cohort"
            and isinstance(self.query.breakdownFilter.breakdown, list)
            and len(self.query.breakdownFilter.breakdown) > 1
            and not any(value == "all" for value in self.query.breakdownFilter.breakdown)
        ):
            self.modifiers.inCohortVia = InCohortVia.LEFTJOIN_CONJOINED

        datawarehouse_modifiers = []
        for series in self.query.series:
            if isinstance(series, DataWarehouseNode):
                datawarehouse_modifiers.append(
                    DataWarehouseEventsModifier(
                        table_name=series.table_name,
                        timestamp_field=series.timestamp_field,
                        id_field=series.id_field,
                        distinct_id_field=series.distinct_id_field,
                    )
                )

        self.modifiers.dataWarehouseEventsModifiers = datawarehouse_modifiers

    def setup_series(self) -> list[SeriesWithExtras]:
        series_with_extras = [
            SeriesWithExtras(
                series=series,
                series_order=index,
                is_previous_period_series=None,
                overriden_query=None,
                aggregate_values=self._trends_display.is_total_value(),
            )
            for index, series in enumerate(self.query.series)
        ]

        if (
            self.modifiers.inCohortVia != InCohortVia.LEFTJOIN_CONJOINED
            and self.query.breakdownFilter is not None
            and self.query.breakdownFilter.breakdown_type == "cohort"
        ):
            updated_series = []
            if isinstance(self.query.breakdownFilter.breakdown, list):
                cohort_ids = self.query.breakdownFilter.breakdown
            elif self.query.breakdownFilter.breakdown is not None:
                cohort_ids = [self.query.breakdownFilter.breakdown]
            else:
                cohort_ids = []

            for cohort_id in cohort_ids:
                for series in series_with_extras:
                    copied_query = deepcopy(self.query)
                    if copied_query.breakdownFilter is not None:
                        copied_query.breakdownFilter.breakdown = cohort_id

                    updated_series.append(
                        SeriesWithExtras(
                            series=series.series,
                            series_order=series.series_order,
                            is_previous_period_series=series.is_previous_period_series,
                            overriden_query=copied_query,
                            aggregate_values=self._trends_display.is_total_value(),
                        )
                    )
            series_with_extras = updated_series

        if self.query.compareFilter is not None and self.query.compareFilter.compare:
            updated_series = []
            for series in series_with_extras:
                updated_series.append(
                    SeriesWithExtras(
                        series=series.series,
                        series_order=series.series_order,
                        is_previous_period_series=False,
                        overriden_query=series.overriden_query,
                        aggregate_values=self._trends_display.is_total_value(),
                    )
                )
            for series in series_with_extras:
                updated_series.append(
                    SeriesWithExtras(
                        series=series.series,
                        series_order=series.series_order,
                        is_previous_period_series=True,
                        overriden_query=series.overriden_query,
                        aggregate_values=self._trends_display.is_total_value(),
                    )
                )

            series_with_extras = updated_series

        return series_with_extras

    def apply_formula(
        self, formula_node: TrendsFormulaNode, results: list[list[dict[str, Any]]], in_breakdown_clause=False
    ) -> list[dict[str, Any]]:
        has_compare = bool(self.query.compareFilter and self.query.compareFilter.compare)
        has_breakdown = self.breakdown_enabled
        is_total_value = self._trends_display.is_total_value()

        if len(results) == 0:
            return []

        # The "all" cohort makes us do special handling (basically we run a separate query per cohort,
        # search for leftjoin_conjoined in self.setup_series). Here we undo the damage.
        if (
            has_breakdown
            and self.query.breakdownFilter
            and self.query.breakdownFilter.breakdown_type == "cohort"
            and isinstance(self.query.breakdownFilter.breakdown, list)
            and "all" in self.query.breakdownFilter.breakdown
            and self.modifiers.inCohortVia != InCohortVia.LEFTJOIN_CONJOINED
            and not in_breakdown_clause
            and self.query.trendsFilter
        ):
            cohort_count = len(self.query.breakdownFilter.breakdown)

            if len(results) % cohort_count == 0:
                results_per_cohort = len(results) // cohort_count
                conjoined_results = []
                for i in range(cohort_count):
                    cohort_series = results[(i * results_per_cohort) : ((i + 1) * results_per_cohort)]
                    cohort_results = self.apply_formula(
                        formula_node,
                        cohort_series,
                        in_breakdown_clause=True,
                    )
                    conjoined_results.extend(cohort_results)
                return conjoined_results
            else:
                raise ValueError("Number of results is not divisible by breakdowns count")

        # we need to apply the formula to a group of results when we have a breakdown or the compare option is enabled
        if has_compare or has_breakdown:
            keys = ["breakdown_value"] if has_breakdown else ["compare_label"]

            all_breakdown_values = set()
            for result in results:
                if isinstance(result, list):
                    for item in result:
                        data = itemgetter(*keys)(item)
                        all_breakdown_values.add(tuple(data) if isinstance(data, list) else data)

            # sort the results so that the breakdown values are in the correct order
            sorted_breakdown_values = natsorted(list(all_breakdown_values), alg=ns.IGNORECASE)

            computed_results = []
            for single_or_multiple_breakdown_value in sorted_breakdown_values:
                breakdown_value = (
                    list(single_or_multiple_breakdown_value)
                    if isinstance(single_or_multiple_breakdown_value, tuple)
                    else single_or_multiple_breakdown_value
                )

                any_result: Optional[dict[str, Any]] = None
                for result in results:
                    matching_result = [item for item in result if itemgetter(*keys)(item) == breakdown_value]
                    if matching_result:
                        any_result = matching_result[0]
                        break
                if not any_result:
                    continue
                row_results = []
                for result in results:
                    matching_result = [item for item in result if itemgetter(*keys)(item) == breakdown_value]
                    if matching_result:
                        # Create a deep copy of the matching result to avoid modifying shared data
                        row_results.append(deepcopy(matching_result[0]))
                    else:
                        row_results.append(
                            {
                                "label": f"filler for {breakdown_value}",
                                "data": [0] * len(results[0][0].get("data") or any_result.get("data") or []),
                                "count": 0,
                                "aggregated_value": 0,
                                "action": None,
                                "breakdown_value": any_result.get("breakdown_value"),
                                "compare_label": any_result.get("compare_label"),
                                "days": any_result.get("days"),
                                "labels": any_result.get("labels"),
                            }
                        )
                new_result = self.apply_formula_to_results_group(
                    row_results, formula_node, breakdown_value=breakdown_value, aggregate_values=is_total_value
                )
                computed_results.append(new_result)

            if has_compare:
                return multisort(computed_results, (("compare_label", False), ("count", True)))

            return sorted(
                computed_results,
                key=lambda s: (
                    (
                        0
                        if s.get("breakdown_value") not in (BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL)
                        else -1
                        if s["breakdown_value"] == BREAKDOWN_NULL_STRING_LABEL
                        else -2
                    ),
                    s.get("aggregated_value", sum(s.get("data") or [])),
                    s.get("count"),
                    s.get("data"),
                    repr(s.get("breakdown_value")),
                ),
                reverse=True,
            )
        else:
            # Create a deep copy of the results to avoid modifying shared data
            copied_results = [[deepcopy(r[0]) for r in results]]
            return [
                self.apply_formula_to_results_group(copied_results[0], formula_node, aggregate_values=is_total_value)
            ]

    @staticmethod
    def apply_formula_to_results_group(
        results_group: list[dict[str, Any]],
        formula_node: TrendsFormulaNode,
        *,
        breakdown_value: Any = None,
        aggregate_values: Optional[bool] = False,
    ) -> dict[str, Any]:
        """
        Applies the formula to a list of results, resulting in a single, computed result.
        """
        formula = formula_node.formula
        base_result = results_group[0]
        base_result["label"] = formula_node.custom_name or f"Formula ({formula})"
        base_result["action"] = None

        if aggregate_values:
            series_data = [[s["aggregated_value"]] for s in results_group]
            new_series_data = FormulaAST(series_data).call(formula)
            base_result["aggregated_value"] = float(sum(new_series_data))
            base_result["data"] = None
            base_result["count"] = 0
        else:
            series_data = [s["data"] for s in results_group]
            new_series_data = FormulaAST(series_data).call(formula)
            base_result["data"] = new_series_data
            base_result["count"] = float(sum(new_series_data))

        return base_result

    def _is_breakdown_filter_field_boolean(self):
        if (
            not self.query.breakdownFilter
            or not self.query.breakdownFilter.breakdown_type
            or not self.query.breakdownFilter.breakdown
        ):
            return False

        if (
            isinstance(self.query.series[0], DataWarehouseNode)
            and self.query.breakdownFilter.breakdown_type == "data_warehouse"
        ):
            series = self.query.series[0]  # only one series when data warehouse is active

            table_or_view = get_view_or_table_by_name(self.team, series.table_name)

            if not table_or_view:
                raise ValueError(f"Table {series.table_name} not found")

            breakdown_key = (
                self.query.breakdownFilter.breakdown[0]
                if isinstance(self.query.breakdownFilter.breakdown, list)
                else self.query.breakdownFilter.breakdown
            )

            if breakdown_key not in dict(table_or_view.columns):
                return False

            field_type = dict(table_or_view.columns)[breakdown_key]["clickhouse"]

            if field_type.startswith("Nullable("):
                field_type = field_type.replace("Nullable(", "")[:-1]

            if field_type == "Bool":
                return True

        return self._is_breakdown_field_boolean(
            self.query.breakdownFilter.breakdown,
            self.query.breakdownFilter.breakdown_type,
            self.query.breakdownFilter.breakdown_group_type_index,
        )

    def _is_breakdown_field_boolean(
        self,
        breakdown_value: str | int | list[str | int],
        breakdown_type: BreakdownType | MultipleBreakdownType | None,
        breakdown_group_type_index: int | None = None,
    ):
        if breakdown_type == "hogql" or breakdown_type == "cohort" or breakdown_type == "session":
            return False

        if breakdown_type == "person":
            property_type = PropertyDefinition.Type.PERSON
        elif breakdown_type == "group":
            property_type = PropertyDefinition.Type.GROUP
        else:
            property_type = PropertyDefinition.Type.EVENT

        field_type = self._event_property(
            str(breakdown_value),
            property_type,
            breakdown_group_type_index,
        )

        return field_type == "Boolean"

    def _convert_boolean(self, value: Any):
        bool_map = {1: "true", 0: "false", "": "", "1": "true", "0": "false"}
        return bool_map.get(value) or value

    def _event_property(
        self,
        field: str,
        field_type: PropertyDefinition.Type,
        group_type_index: Optional[int],
    ) -> str:
        try:
            return (
                PropertyDefinition.objects.alias(
                    effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
                )
                .get(
                    effective_project_id=self.team.project_id,
                    name=field,
                    type=field_type,
                    group_type_index=group_type_index if field_type == PropertyDefinition.Type.GROUP else None,
                )
                .property_type
                or "String"
            )
        except PropertyDefinition.DoesNotExist:
            return "String"

    # TODO: Move this to posthog/hogql_queries/legacy_compatibility/query_to_filter.py
    def _query_to_filter(self) -> dict[str, Any]:
        filter_dict = {
            "insight": "TRENDS",
            "properties": self.query.properties,
            "filter_test_accounts": self.query.filterTestAccounts,
            "date_to": self.query_date_range.date_to(),
            "date_from": self.query_date_range.date_from(),
            "entity_type": "events",
            "sampling_factor": self.query.samplingFactor,
            "aggregation_group_type_index": self.query.aggregation_group_type_index,
            "interval": self.query.interval,
        }

        if self.query.trendsFilter is not None:
            filter_dict.update(self.query.trendsFilter.__dict__)

        if self.query.breakdownFilter is not None:
            filter_dict.update(**self.query.breakdownFilter.__dict__)

        return {k: v for k, v in filter_dict.items() if v is not None}

    @cached_property
    def _trends_display(self) -> TrendsDisplay:
        if self.query.trendsFilter is None or self.query.trendsFilter.display is None:
            display = ChartDisplayType.ACTIONS_LINE_GRAPH
        else:
            display = self.query.trendsFilter.display

        return TrendsDisplay(display)

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter):
        super().apply_dashboard_filters(dashboard_filter=dashboard_filter)

        if (
            self.query.compareFilter is not None
            and self.query.compareFilter.compare
            and dashboard_filter.date_from == "all"
        ):
            # TODO: Move this "All time" range handling out of `apply_dashboard_filters` – if the date range is "all",
            # we should disable `compare` _no matter how_ we arrived at the final executed query
            self.query.compareFilter.compare = False

    def _format_breakdown_label(self, breakdown_value: Any):
        if self.query.breakdownFilter is not None and self.query.breakdownFilter.breakdowns is not None:
            labels = []
            for breakdown, label in zip(self.query.breakdownFilter.breakdowns, breakdown_value):
                if self._is_breakdown_field_boolean(breakdown.property, breakdown.type, breakdown.group_type_index):
                    labels.append(self._convert_boolean(label))
                else:
                    labels.append(label)

            # Mirrors the frontend formatting
            return "::".join(labels)
        return breakdown_value

    @cached_property
    def breakdown_enabled(self):
        return self.query.breakdownFilter is not None and (
            self.query.breakdownFilter.breakdown is not None
            or (self.query.breakdownFilter.breakdowns is not None and len(self.query.breakdownFilter.breakdowns) > 0)
        )

    def _get_breakdown_items(
        self,
        breakdown_values: list[str],
        breakdown_value: str | int | list[int | str],
        breakdown_type: MultipleBreakdownType | BreakdownType | None,
        histogram_breakdown: bool | None = None,
        group_type_index: int | None = None,
        # Overwrite for data warehouse queries
        is_boolean_field: bool | None = None,
    ):
        if histogram_breakdown:
            breakdown_values.append(BREAKDOWN_NUMERIC_ALL_VALUES_PLACEHOLDER)

            if BREAKDOWN_OTHER_STRING_LABEL in breakdown_values:
                breakdown_values.remove(BREAKDOWN_OTHER_STRING_LABEL)
                breakdown_values.append(BREAKDOWN_OTHER_STRING_LABEL)

            if BREAKDOWN_NULL_STRING_LABEL in breakdown_values:
                breakdown_values.remove(BREAKDOWN_NULL_STRING_LABEL)
                breakdown_values.append(BREAKDOWN_NULL_STRING_LABEL)

        res_breakdown: list[BreakdownItem] = []
        for value in breakdown_values:
            if value == BREAKDOWN_OTHER_STRING_LABEL:
                label = BREAKDOWN_OTHER_DISPLAY
            elif value == BREAKDOWN_NULL_STRING_LABEL:
                label = BREAKDOWN_NULL_DISPLAY
            elif (
                self._is_breakdown_field_boolean(
                    breakdown_value, breakdown_type, breakdown_group_type_index=group_type_index
                )
                or is_boolean_field
            ):
                label = self._convert_boolean(value)
            else:
                label = str(value)

            item = BreakdownItem(label=label, value=value)

            if item not in res_breakdown:
                res_breakdown.append(item)

        return res_breakdown

    def _is_other_breakdown(self, breakdown: str | list[str]) -> bool:
        return (
            breakdown == BREAKDOWN_OTHER_STRING_LABEL
            or isinstance(breakdown, list)
            and BREAKDOWN_OTHER_STRING_LABEL in breakdown
        )
