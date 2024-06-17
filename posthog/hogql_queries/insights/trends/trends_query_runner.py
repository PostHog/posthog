import types

import structlog
from natsort import natsorted, ns
from typing import Union
from copy import deepcopy
from datetime import timedelta
from math import ceil
from operator import itemgetter
import threading
from typing import Optional, Any
from django.conf import settings

from django.utils.timezone import datetime
from prometheus_client import Counter

from posthog import utils
from posthog.cache_utils import OrjsonJsonSerializer
from posthog.caching.insights_api import (
    BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL,
    REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL,
    REAL_TIME_INSIGHT_REFRESH_INTERVAL,
)
from posthog.caching.utils import is_stale
from posthog.clickhouse import query_tagging

from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery, SelectUnionQuery
from posthog.hogql.constants import LimitContext, MAX_SELECT_RETURNED_ROWS, BREAKDOWN_VALUES_LIMIT
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.display import TrendsDisplay
from posthog.hogql_queries.insights.trends.breakdown import (
    BREAKDOWN_NULL_DISPLAY,
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_DISPLAY,
    BREAKDOWN_OTHER_STRING_LABEL,
)
from posthog.hogql_queries.insights.trends.trends_query_builder import TrendsQueryBuilder
from posthog.hogql_queries.insights.trends.trends_actors_query_builder import TrendsActorsQueryBuilder
from posthog.hogql_queries.insights.trends.series_with_extras import SeriesWithExtras
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.formula_ast import FormulaAST
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import (
    QueryPreviousPeriodDateRange,
)
from posthog.models import Team
from posthog.models.action.action import Action
from posthog.models.cohort.cohort import Cohort
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property_definition import PropertyDefinition
from posthog.queries.util import correct_result_for_sampling
from posthog.schema import (
    ActionsNode,
    BreakdownItem,
    CachedTrendsQueryResponse,
    ChartDisplayType,
    Compare,
    CompareItem,
    DashboardFilter,
    DayItem,
    EventsNode,
    DataWarehouseNode,
    HogQLQueryResponse,
    InCohortVia,
    InsightActorsQueryOptionsResponse,
    QueryTiming,
    Series,
    TrendsQuery,
    TrendsQueryResponse,
    HogQLQueryModifiers,
    DataWarehouseEventsModifier,
    BreakdownType,
)
from posthog.settings import TEST
from posthog.warehouse.models import DataWarehouseTable
from posthog.utils import format_label_date, multisort, relative_date_parse_with_delta_mapping

TRENDS_CALCULATE_FROM_CACHE_SKIP_COUNT = Counter(
    "trends_calculate_from_cache_skip_count",
    "Number of trends that skipped calculation from cache",
)

TRENDS_CALCULATE_FROM_CACHE_FAILURE_COUNT = Counter(
    "trends_calculate_from_cache_failure_count",
    "Number of trends that failed while calculating from cache",
)

TRENDS_CALCULATE_FROM_CACHE_SUCCESS_COUNT = Counter(
    "trends_calculate_from_cache_success_count",
    "Number of trends that succeeded while calculating from cache",
)

logger = structlog.get_logger(__name__)


class TrendsQueryRunner(QueryRunner):
    query: TrendsQuery
    response: TrendsQueryResponse
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
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)
        self.update_hogql_modifiers()
        self.series = self.setup_series()

    def _is_stale(self, cached_result_package):
        date_to = self.query_date_range.date_to()
        interval = self.query_date_range.interval_name
        return is_stale(self.team, date_to, interval, cached_result_package)

    def can_compute_from_cache(self):
        if not isinstance(self.cached_response, CachedTrendsQueryResponse):
            return False

        if not self.query_can_compute_from_cache():
            return False

        # todo: write test to see how this works with something that shouldn't be aligned (-72h)
        # it fails
        # this means this fails with weeks and with days?
        aligned_last_refresh = self.query_date_range.align_with_interval(self.cached_response.last_refresh)

        # If more time has passed since the last refresh than the daterange, don't use caching
        too_much_time_has_passed = (datetime.now(self.team.timezone_info) - aligned_last_refresh) > (
            self.query_date_range.date_to() - self.query_date_range.date_from()
        )

        return not too_much_time_has_passed

    def query_can_compute_from_cache(self):
        # Only support cache computation for queries that are relative to now
        is_relative = self.query.dateRange is None or (
            self.query.dateRange.date_to is None
            and (
                # We don't support queries that are relative to a fixed date with compare set to True, because we would
                # have to expand the compare window backwards in time. It either has a delta mapping, or it doesn't have a compare
                (
                    self.query.dateRange.date_from
                    and relative_date_parse_with_delta_mapping(self.query.dateRange.date_from, self.team.timezone_info)[
                        1
                    ]
                )
                or not self.query.compareFilter
                or not self.query.compareFilter.compare
            )
        )

        # For now, we only support date_ranges if they use the start of the interval
        # We can make this work without, but we'd have to query for changes to the beginning of the time range also
        use_start_of_interval = self.query_date_range.use_start_of_interval()

        query_interval_is_long_enough = self.query_date_range.n_intervals_in_date_range() > 1

        # we don't support histogram_bin_counts at the moment because this queries the events to generate the breakdown values
        uses_histogram_bin_count = (
            self.query.breakdownFilter is not None
            and self.query.breakdownFilter.breakdown is not None
            and self.query.breakdownFilter.breakdown_histogram_bin_count is not None
        )

        # We also don't support smoothing, but if it's a big case could look into supporting it (increasing date range for caching might be enough)
        uses_smoothing = self.query.trendsFilter is not None and self.query.trendsFilter.smoothingIntervals not in (
            1,
            None,
        )

        # TODO: Make this work for breakdown limits as long as we aren't hitting them
        uses_breakdown_limit = (
            self.query.breakdownFilter is not None
            and self.query.breakdownFilter.breakdown is not None
            and self.query.breakdownFilter.breakdown_limit is not None
        )

        # Currently doesn't work for total value. Consider nixing total value on the backend and computing it on the front-end for performance improvements.
        total_value = self.query.trendsFilter is not None and self.query.trendsFilter.display in (
            ChartDisplayType.BOLD_NUMBER,
            ChartDisplayType.WORLD_MAP,
            ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE,
            ChartDisplayType.ACTIONS_BAR_VALUE,
            ChartDisplayType.ACTIONS_PIE,
        )

        # This might overlap with the previous check a bit
        # Don't try to compute caching for aggregate values
        aggregate_values = any(x.aggregate_values for x in self.series)

        return (
            is_relative
            and use_start_of_interval
            and query_interval_is_long_enough
            and not uses_histogram_bin_count
            and not uses_smoothing
            and not uses_breakdown_limit
            and not total_value
            and not aggregate_values
        )

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

    def to_query(self) -> ast.SelectUnionQuery:
        queries = []
        for query in self.to_queries():
            if isinstance(query, ast.SelectQuery):
                queries.append(query)
            else:
                queries.extend(query.select_queries)
        return ast.SelectUnionQuery(select_queries=queries)

    def to_queries(self) -> list[ast.SelectQuery | ast.SelectUnionQuery]:
        queries = []
        with self.timings.measure("trends_to_query"):
            for series in self.series:
                if not series.is_previous_period_series:
                    query_date_range = self.query_date_range
                else:
                    query_date_range = self.query_previous_date_range

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

    def to_cached_queries(self, skip_breakdowns=False) -> list[ast.SelectQuery | ast.SelectUnionQuery]:
        queries = []
        aligned_last_refresh = self.query_date_range.align_with_interval(
            self.cached_response.last_refresh.astimezone(self.team.timezone_info)
        )

        for series in self.series:
            # Override "date_from" to only look at the interval of time starting at the last refresh
            if not series.is_previous_period_series:
                query_date_range = QueryDateRange(
                    *[
                        getattr(self.query_date_range, x)
                        for x in ["_date_range", "_team", "_interval", "_now_without_timezone"]
                    ]
                )
                self.cached_query_date_range = query_date_range
                new_date_from = aligned_last_refresh
            else:
                query_date_range = QueryPreviousPeriodDateRange(
                    *[
                        getattr(self.query_previous_date_range, x)
                        for x in ["_date_range", "_team", "_interval", "_now_without_timezone"]
                    ]
                )
                self.cached_query_previous_date_range = query_date_range
                new_date_from = self.query_previous_date_range.date_from() + (
                    aligned_last_refresh - self.query_date_range.date_from()
                )
            query_date_range.date_from = types.MethodType(  # type: ignore
                lambda self, new_date_from=new_date_from: new_date_from, query_date_range
            )

            trends_query = series.overriden_query or self.query
            if skip_breakdowns:
                trends_query.breakdownFilter = None

            query_builder = TrendsQueryBuilder(
                trends_query=trends_query,
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

    def to_actors_query(
        self,
        time_frame: Optional[str],
        series_index: int,
        breakdown_value: Optional[str | int] = None,
        compare_value: Optional[Compare] = None,
        include_recordings: Optional[bool] = None,
    ) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("trends_to_actors_query"):
            if self.query.breakdownFilter and self.query.breakdownFilter.breakdown_type == BreakdownType.COHORT:
                if self.query.breakdownFilter.breakdown in ("all", ["all"]) or breakdown_value == "all":
                    self.query.breakdownFilter = None
                elif isinstance(self.query.breakdownFilter.breakdown, list):
                    self.query.breakdownFilter.breakdown = [
                        x for x in self.query.breakdownFilter.breakdown if x != "all"
                    ]
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

            query = query_builder.build_actors_query()

        return query

    def to_actors_query_options(self) -> InsightActorsQueryOptionsResponse:
        res_breakdown: list[BreakdownItem] | None = None
        res_series: list[Series] = []
        res_compare: list[CompareItem] | None = None

        # Days
        res_days: Optional[list[DayItem]] = (
            None
            if self._trends_display.is_total_value()
            else [
                DayItem(
                    label=format_label_date(value, self.query_date_range.interval_name),
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
        if self.query.breakdownFilter is not None and self.query.breakdownFilter.breakdown is not None:
            res_breakdown = []
            if self.query.breakdownFilter.breakdown_type == "cohort":
                assert isinstance(self.query.breakdownFilter.breakdown, list)
                for value in self.query.breakdownFilter.breakdown:
                    if value != "all" and str(value) != "0":
                        res_breakdown.append(
                            BreakdownItem(label=Cohort.objects.get(pk=int(value), team=self.team).name, value=value)
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

                breakdown = query_builder._breakdown(is_actors_query=False)

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

                if breakdown.is_histogram_breakdown:
                    breakdown_values.append('["",""]')
                is_boolean_breakdown = self._is_breakdown_field_boolean()

                for value in breakdown_values:
                    if value == BREAKDOWN_OTHER_STRING_LABEL:
                        label = BREAKDOWN_OTHER_DISPLAY
                    elif value == BREAKDOWN_NULL_STRING_LABEL:
                        label = BREAKDOWN_NULL_DISPLAY
                    elif is_boolean_breakdown:
                        label = self._convert_boolean(value)
                    else:
                        label = str(value)

                    item = BreakdownItem(label=label, value=value)

                    if item not in res_breakdown:
                        res_breakdown.append(item)

        return InsightActorsQueryOptionsResponse(
            series=res_series, breakdown=res_breakdown, day=res_days, compare=res_compare
        )

    def _process_result(self, res_matrix):
        # Flatten res and timings
        returned_results: list[list[dict[str, Any]]] = []
        for result in res_matrix:
            if isinstance(result, list):
                returned_results.append(result)
            elif isinstance(result, dict):
                returned_results.append([result])

        if (
            self.query.trendsFilter is not None
            and self.query.trendsFilter.formula is not None
            and self.query.trendsFilter.formula != ""
        ):
            with self.timings.measure("apply_formula"):
                has_compare = bool(self.query.compareFilter and self.query.compareFilter.compare)
                if has_compare:
                    current_results = returned_results[: len(returned_results) // 2]
                    previous_results = returned_results[len(returned_results) // 2 :]

                    final_result = self.apply_formula(
                        self.query.trendsFilter.formula, current_results
                    ) + self.apply_formula(self.query.trendsFilter.formula, previous_results)
                else:
                    final_result = self.apply_formula(self.query.trendsFilter.formula, returned_results)
        else:
            final_result = []
            for result in returned_results:
                if isinstance(result, list):
                    final_result.extend(result)
                elif isinstance(result, dict):
                    raise ValueError("This should not happen")

        return final_result

    def _process_timings(self, timings_matrix):
        timings: list[QueryTiming] = []
        for timing in timings_matrix:
            if isinstance(timing, list):
                timings.extend(timing)
        return timings

    def calculate(self):
        queries = self.to_queries()

        if len(queries) == 1:
            response_hogql_query = queries[0]
        else:
            response_hogql_query = ast.SelectUnionQuery(select_queries=[])
            for query in queries:
                if isinstance(query, ast.SelectQuery):
                    response_hogql_query.select_queries.append(query)
                else:
                    response_hogql_query.select_queries.extend(query.select_queries)

        with self.timings.measure("printing_hogql_for_response"):
            response_hogql = to_printed_hogql(response_hogql_query, self.team, self.modifiers)

        res_matrix: list[list[Any] | Any | None] = [None] * len(queries)
        timings_matrix: list[list[QueryTiming] | None] = [None] * len(queries)
        errors: list[Exception] = []
        debug_errors: list[str] = []

        use_caching = self.can_compute_from_cache()
        caching_queries: list[SelectQuery | SelectUnionQuery]
        caching_res_matrix: list[list[Any] | Any | None]
        caching_timings_matrix: list[list[QueryTiming] | None] = [None] * len(queries)
        caching_errors: list[Exception] = []
        caching_debug_errors: list[str] = []
        if use_caching:
            caching_queries = self.to_cached_queries()
            caching_res_matrix = [None] * len(queries)
            caching_timings_matrix = [None] * len(queries)
            caching_errors = []
            caching_debug_errors = []
        else:
            TRENDS_CALCULATE_FROM_CACHE_SKIP_COUNT.inc()

        def run_queries():
            def run(index: int, is_parallel: bool, query_tags: Optional[dict] = None):
                try:
                    if query_tags:
                        query_tagging.tag_queries(**query_tags)

                    series_with_extra = self.series[index]

                    response = execute_hogql_query(
                        query_type="TrendsQuery",
                        query=queries[index],
                        team=self.team,
                        timings=self.timings,
                        modifiers=self.modifiers,
                        limit_context=self.limit_context,
                    )

                    timings_matrix[index] = response.timings
                    res_matrix[index] = self.build_series_response(response, series_with_extra, len(queries))
                    if response.error:
                        debug_errors.append(response.error)

                    # Put caching query in line with normal query, since it will access the same data
                    if use_caching:
                        try:
                            response = execute_hogql_query(
                                query_type="TrendsQuery",
                                query=caching_queries[index],
                                team=self.team,
                                timings=self.timings,
                                modifiers=self.modifiers,
                                limit_context=self.limit_context,
                            )

                            caching_timings_matrix[index] = response.timings
                            caching_res_matrix[index] = self.build_series_response(
                                response, series_with_extra, len(queries)
                            )
                            if response.error:
                                caching_debug_errors.append(response.error)
                        except Exception as e:
                            caching_errors.append(e)
                except Exception as e:
                    errors.append(e)
                finally:
                    if is_parallel:
                        from django.db import connection

                        # This will only close the DB connection for the newly spawned thread and not the whole app
                        connection.close()

            # This exists so that we're not spawning threads during unit tests. We can't do
            # this right now due to the lack of multithreaded support of Django
            if settings.IN_UNIT_TESTING:
                for index in range(len(queries)):
                    run(index, False)
            elif len(queries) == 1:
                run(0, False)
            else:
                jobs = [
                    threading.Thread(target=run, args=(index, True, query_tagging.get_query_tags()))
                    for index in range(len(queries))
                ]
                [j.start() for j in jobs]  # type: ignore
                [j.join() for j in jobs]  # type: ignore

        run_queries()

        # Raise any errors raised in a seperate thread
        if len(errors) > 0:
            raise errors[0]

        processed_actual_results = self._process_result(res_matrix)
        processed_timings = self._process_timings(timings_matrix)

        # don't mess with caching if there is only one interval
        if use_caching:
            try:
                self._caching(
                    caching_res_matrix,
                    caching_timings_matrix,
                    caching_errors,
                    caching_debug_errors,
                    processed_actual_results,
                )
            except Exception as e:
                if TEST:
                    raise e
                logger.error("TRENDS_CALCULATE_FROM_CACHE_FAILURE", error=e)
                TRENDS_CALCULATE_FROM_CACHE_FAILURE_COUNT.inc()

        return TrendsQueryResponse(
            results=processed_actual_results,
            timings=processed_timings,
            hogql=response_hogql,
            modifiers=self.modifiers,
            error=". ".join(debug_errors),
        )

    def _caching(
        self,
        caching_res_matrix,
        caching_timings_matrix,
        caching_errors,
        caching_debug_errors,
        processed_actual_results,
    ):
        if len(caching_errors) > 0 or len(caching_debug_errors) > 0:
            # This function is called in a try, so this will be caught and reported
            raise Exception("\n".join(caching_errors) + "\n".join(caching_debug_errors))

        # Now the goal is the reconstitute the cached query and compare against results

        composed_results = []

        processed_cached_results = self._process_result(caching_res_matrix)

        for results, caching_results in zip(
            [self.cached_response.results],
            [processed_cached_results],
        ):
            # if we are using a breakdown and the results are 0, we return nothing
            if (
                self.query.breakdownFilter is not None
                and self.query.breakdownFilter.breakdown is not None
                and (len(results) == 0 or all(all(x == 0 for x in result["data"]) for result in results))
                and (
                    len(caching_results) == 0 or all(all(x == 0 for x in result["data"]) for result in caching_results)
                )
            ):
                continue

            def unique_result_key(result):
                return (
                    result.get("label"),
                    result.get("breakdown_value"),
                    result.get("compare_label"),
                    (result.get("action", {}) or {}).get("order", 0),
                )

            results_dict = {unique_result_key(x): x for x in results}
            caching_results_dict = {unique_result_key(x): x for x in caching_results}

            defaults: dict[tuple[str, str] | str, Any] = {}
            for k, data in (("cache", caching_results), ("results", results)):
                for result in data:
                    if result["days"] != []:
                        defaults[(k, result.get("compare_label"))] = result
                        defaults[k] = result

            for dict_key in set(results_dict.keys()).union(caching_results_dict.keys()):
                (label, breakdown_value, compare, series) = dict_key

                result = results_dict.get(dict_key)
                caching_result = caching_results_dict.get(dict_key)

                query_date_range = self.query_previous_date_range if compare == "previous" else self.query_date_range

                cached_query_date_range = (
                    self.cached_query_previous_date_range if compare == "previous" else self.cached_query_date_range
                )

                dates = query_date_range.all_values()
                result_length = len(dates)
                cached_dates = cached_query_date_range.all_values()
                caching_results_length = len(cached_dates)
                old_results_to_carry_over = result_length - caching_results_length

                if caching_results_length != 0:
                    first_day = cached_dates[0].strftime(
                        "%Y-%m-%d{}".format(
                            " %H:%M:%S" if self.query_date_range.interval_name in ("hour", "minute") else ""
                        )
                    )
                    if defaults.get(("results", compare)) is not None:
                        results_last_index = defaults[("results", compare)]["days"].index(first_day)
                else:
                    results_last_index = result_length

                composed_result = {}
                # Data
                caching_v = caching_result["data"] if caching_result is not None else [0] * caching_results_length
                result_v = (
                    result["data"][results_last_index - old_results_to_carry_over : results_last_index]
                    if result is not None
                    else [0] * old_results_to_carry_over
                )
                composed_result["data"] = result_v + caching_v

                # Labels
                if self.query.compareFilter is not None and self.query.compareFilter.compare:
                    composed_result["labels"] = [
                        "{} {}".format(
                            self.query_date_range.interval_name,
                            i,
                        )
                        for i in range(result_length)
                    ]
                else:
                    composed_result["labels"] = [
                        utils.format_label_date(x, self.query_date_range.interval_name) for x in dates
                    ]

                # Days
                composed_result["days"] = [
                    x.strftime(
                        "%Y-%m-%d{}".format(
                            " %H:%M:%S" if self.query_date_range.interval_name in ("hour", "minute") else ""
                        )
                    )
                    for x in dates
                ]

                # Filter
                composed_result["filter"] = self._query_to_filter()

                # Action
                if caching_result is not None:
                    composed_result["action"] = caching_result["action"]
                else:
                    composed_result["action"] = result["action"]
                    if composed_result["action"] is not None:
                        composed_result["action"]["days"] = dates

                # Either result or caching result (non exclusive or) will exist
                for k, v in (result or caching_result).items():
                    if k not in ("action", "filter", "days", "data", "labels"):
                        composed_result[k] = v

                composed_result["count"] = float(sum(composed_result["data"]))

                # don't push an empty result if it is a breakdown
                if breakdown_value is not None and composed_result["count"] == 0:
                    continue
                composed_results.append(composed_result)

        key_order = [unique_result_key(x) for x in processed_actual_results]
        composed_results.sort(key=lambda x: key_order.index(unique_result_key(x)))

        json = OrjsonJsonSerializer({})
        actual_json = json.loads(json.dumps(processed_actual_results))
        caching_json = json.loads(json.dumps(composed_results))

        # if any(x["action"]["order"] != 0 for x in actual_json if x is not None and x["action"] is not None):
        # raise Exception

        if TEST:
            assert actual_json == caching_json
        elif actual_json == caching_json:
            TRENDS_CALCULATE_FROM_CACHE_SUCCESS_COUNT.inc()
        else:
            TRENDS_CALCULATE_FROM_CACHE_FAILURE_COUNT.inc()
            logger.error(
                "TRENDS_CALCULATE_FROM_CACHE_FAILURE: Different Json",
                actual_json=actual_json,
                caching_json=caching_json,
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
                        format_label_date(item, self.query_date_range.interval_name) for item in get_value("date", val)
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
                labels = [
                    "{} {}".format(
                        self.query.interval if self.query.interval is not None else "day",
                        i,
                    )
                    for i in range(len(series_object.get("labels", [])))
                ]

                series_object["compare"] = True
                series_object["compare_label"] = "previous" if series.is_previous_period_series else "current"
                series_object["labels"] = labels

            # Modifications for when breakdowns are active
            if self.query.breakdownFilter is not None and self.query.breakdownFilter.breakdown is not None:
                remapped_label = None

                if self._is_breakdown_field_boolean():
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

                    # If there's multiple series, include the object label in the series label
                    if real_series_count > 1:
                        series_object["label"] = "{} - {}".format(series_object["label"], remapped_label)
                    else:
                        series_object["label"] = remapped_label

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

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval,
            now=datetime.now(),
        )

    @cached_property
    def query_previous_date_range(self):
        if self.query.compareFilter is not None and isinstance(self.query.compareFilter.compare_to, str):
            return QueryCompareToDateRange(
                date_range=self.query.dateRange,
                team=self.team,
                interval=self.query.interval,
                now=datetime.now(),
                compare_to=self.query.compareFilter.compare_to,
            )
        return QueryPreviousPeriodDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval,
            now=datetime.now(),
        )

    def series_event(self, series: Union[EventsNode, ActionsNode, DataWarehouseNode]) -> str | None:
        if isinstance(series, EventsNode):
            return series.event
        if isinstance(series, ActionsNode):
            # TODO: Can we load the Action in more efficiently?
            action = Action.objects.get(pk=int(series.id), team=self.team)
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
        self, formula: str, results: list[list[dict[str, Any]]], in_breakdown_clause=False
    ) -> list[dict[str, Any]]:
        has_compare = bool(self.query.compareFilter and self.query.compareFilter.compare)
        has_breakdown = bool(self.query.breakdownFilter and self.query.breakdownFilter.breakdown)
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
            and self.query.trendsFilter.formula
        ):
            cohort_count = len(self.query.breakdownFilter.breakdown)

            if len(results) % cohort_count == 0:
                results_per_cohort = len(results) // cohort_count
                conjoined_results = []
                for i in range(cohort_count):
                    cohort_series = results[(i * results_per_cohort) : ((i + 1) * results_per_cohort)]
                    cohort_results = self.apply_formula(
                        self.query.trendsFilter.formula, cohort_series, in_breakdown_clause=True
                    )
                    conjoined_results.append(cohort_results)
                results = conjoined_results
            else:
                raise ValueError("Number of results is not divisible by breakdowns count")

        # we need to apply the formula to a group of results when we have a breakdown or the compare option is enabled
        if has_compare or has_breakdown:
            keys = ["breakdown_value"] if has_breakdown else ["compare_label"]

            all_breakdown_values = set()
            for result in results:
                if isinstance(result, list):
                    for item in result:
                        all_breakdown_values.add(itemgetter(*keys)(item))

            # sort the results so that the breakdown values are in the correct order
            sorted_breakdown_values = natsorted(list(all_breakdown_values), alg=ns.IGNORECASE)

            computed_results = []
            for breakdown_value in sorted_breakdown_values:
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
                        row_results.append(matching_result[0])
                    else:
                        row_results.append(
                            {
                                "label": f"filler for {breakdown_value}",
                                "data": [0] * len(results[0][0].get("data") or any_result.get("data") or []),
                                "count": 0,
                                "aggregated_value": 0,
                                "action": None,
                                "filter": any_result.get("filter"),
                                "breakdown_value": any_result.get("breakdown_value"),
                                "compare_label": any_result.get("compare_label"),
                                "days": any_result.get("days"),
                                "labels": any_result.get("labels"),
                            }
                        )
                new_result = self.apply_formula_to_results_group(row_results, formula, is_total_value)
                computed_results.append(new_result)

            if has_compare:
                return multisort(computed_results, (("compare_label", False), ("count", True)))

            return sorted(computed_results, key=itemgetter("count"), reverse=True)
        else:
            return [
                self.apply_formula_to_results_group([r[0] for r in results], formula, aggregate_values=is_total_value)
            ]

    @staticmethod
    def apply_formula_to_results_group(
        results_group: list[dict[str, Any]], formula: str, aggregate_values: Optional[bool] = False
    ) -> dict[str, Any]:
        """
        Applies the formula to a list of results, resulting in a single, computed result.
        """
        base_result = results_group[0]
        base_result["label"] = f"Formula ({formula})"
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

    def _is_breakdown_field_boolean(self):
        if not self.query.breakdownFilter or not self.query.breakdownFilter.breakdown_type:
            return False

        if (
            self.query.breakdownFilter.breakdown_type == "hogql"
            or self.query.breakdownFilter.breakdown_type == "cohort"
            or self.query.breakdownFilter.breakdown_type == "session"
        ):
            return False

        if (
            isinstance(self.query.series[0], DataWarehouseNode)
            and self.query.breakdownFilter.breakdown_type == "data_warehouse"
        ):
            series = self.query.series[0]  # only one series when data warehouse is active
            table_model = (
                DataWarehouseTable.objects.filter(name=series.table_name, team=self.team).exclude(deleted=True).first()
            )

            if not table_model:
                raise ValueError(f"Table {series.table_name} not found")

            field_type = dict(table_model.columns)[self.query.breakdownFilter.breakdown]["clickhouse"]

            if field_type.startswith("Nullable("):
                field_type = field_type.replace("Nullable(", "")[:-1]

            if field_type == "Bool":
                return True

        else:
            if self.query.breakdownFilter.breakdown_type == "person":
                property_type = PropertyDefinition.Type.PERSON
            elif self.query.breakdownFilter.breakdown_type == "group":
                property_type = PropertyDefinition.Type.GROUP
            else:
                property_type = PropertyDefinition.Type.EVENT

            field_type = self._event_property(
                self.query.breakdownFilter.breakdown,
                property_type,
                self.query.breakdownFilter.breakdown_group_type_index,
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
                PropertyDefinition.objects.get(
                    name=field,
                    team=self.team,
                    type=field_type,
                    group_type_index=group_type_index if field_type == PropertyDefinition.Type.GROUP else None,
                ).property_type
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
            self.query.breakdownFilter
            and self.query.breakdownFilter.breakdown_limit
            and self.query.breakdownFilter.breakdown_limit > BREAKDOWN_VALUES_LIMIT
        ):
            # Remove too high breakdown limit for display on the dashboard
            self.query.breakdownFilter.breakdown_limit = None

        if (
            self.query.compareFilter is not None
            and self.query.compareFilter.compare
            and dashboard_filter.date_from == "all"
        ):
            # TODO: Move this "All time" range handling out of `apply_dashboard_filters` – if the date range is "all",
            # we should disable `compare` _no matter how_ we arrived at the final executed query
            self.query.compareFilter.compare = False
