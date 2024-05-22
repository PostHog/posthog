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
from posthog.caching.insights_api import (
    BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL,
    REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL,
    REAL_TIME_INSIGHT_REFRESH_INTERVAL,
)
from posthog.caching.utils import is_stale

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext, MAX_SELECT_RETURNED_ROWS, BREAKDOWN_VALUES_LIMIT
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.breakdown_values import (
    BREAKDOWN_NULL_DISPLAY,
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_DISPLAY,
    BREAKDOWN_OTHER_STRING_LABEL,
)
from posthog.hogql_queries.insights.trends.display import TrendsDisplay
from posthog.hogql_queries.insights.trends.trends_query_builder import TrendsQueryBuilder
from posthog.hogql_queries.insights.trends.trends_actors_query_builder import TrendsActorsQueryBuilder
from posthog.hogql_queries.insights.trends.series_with_extras import SeriesWithExtras
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.formula_ast import FormulaAST
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
)
from posthog.warehouse.models import DataWarehouseTable
from posthog.utils import format_label_date, multisort


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

    def to_actors_query(
        self,
        time_frame: Optional[str],
        series_index: int,
        breakdown_value: Optional[str | int] = None,
        compare_value: Optional[Compare] = None,
        include_recordings: Optional[bool] = None,
    ) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("trends_to_actors_query"):
            query_builder = TrendsActorsQueryBuilder(
                trends_query=self.query,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
                # actors related args
                time_frame=time_frame,
                series_index=series_index,
                breakdown_value=breakdown_value,
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
        if self.query.trendsFilter is not None and self.query.trendsFilter.compare:
            res_compare = [
                CompareItem(label="Current", value="current"),
                CompareItem(label="Previous", value="previous"),
            ]

        # Breakdowns
        for series in self.query.series:
            # TODO: Add support for DataWarehouseNode
            if isinstance(series, DataWarehouseNode):
                continue

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

            breakdown = query_builder._breakdown(is_actors_query=False)
            if not breakdown.enabled:
                break

            is_boolean_breakdown = self._is_breakdown_field_boolean()
            is_histogram_breakdown = breakdown.is_histogram_breakdown
            breakdown_values: list[str | int]
            res_breakdown = []

            if is_histogram_breakdown:
                buckets = breakdown._get_breakdown_histogram_buckets()
                breakdown_values = [f"[{t[0]},{t[1]}]" for t in buckets]
                # TODO: append this only if needed
                breakdown_values.append('["",""]')
            else:
                breakdown_values = breakdown._breakdown_values

            for value in breakdown_values:
                if self.query.breakdownFilter is not None and self.query.breakdownFilter.breakdown_type == "cohort":
                    cohort_name = "all users" if str(value) == "0" else Cohort.objects.get(pk=value).name
                    label = cohort_name
                    value = value
                elif value == BREAKDOWN_OTHER_STRING_LABEL:
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

        def run(index: int, query: ast.SelectQuery | ast.SelectUnionQuery, is_parallel: bool):
            try:
                series_with_extra = self.series[index]

                response = execute_hogql_query(
                    query_type="TrendsQuery",
                    query=query,
                    team=self.team,
                    timings=self.timings,
                    modifiers=self.modifiers,
                    limit_context=self.limit_context,
                )

                timings_matrix[index] = response.timings
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

        # This exists so that we're not spawning threads during unit tests. We can't do
        # this right now due to the lack of multithreaded support of Django
        if settings.IN_UNIT_TESTING:
            for index, query in enumerate(queries):
                run(index, query, False)
        elif len(queries) == 1:
            run(0, queries[0], False)
        else:
            jobs = [threading.Thread(target=run, args=(index, query, True)) for index, query in enumerate(queries)]

            # Start the threads
            for j in jobs:
                j.start()

            # Ensure all of the threads have finished
            for j in jobs:
                j.join()

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

        timings: list[QueryTiming] = []
        for timing in timings_matrix:
            if isinstance(timing, list):
                timings.extend(timing)

        if (
            self.query.trendsFilter is not None
            and self.query.trendsFilter.formula is not None
            and self.query.trendsFilter.formula != ""
        ):
            with self.timings.measure("apply_formula"):
                has_compare = bool(self.query.trendsFilter and self.query.trendsFilter.compare)
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

        return TrendsQueryResponse(
            results=final_result,
            timings=timings,
            hogql=response_hogql,
            modifiers=self.modifiers,
            error=". ".join(debug_errors),
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
        if self.query.trendsFilter is not None and self.query.trendsFilter.compare:
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
                if self._trends_display.display_type == ChartDisplayType.ActionsLineGraphCumulative:
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
            if self.query.trendsFilter is not None and self.query.trendsFilter.compare:
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
            self.modifiers.inCohortVia == InCohortVia.auto
            and self.query.breakdownFilter is not None
            and self.query.breakdownFilter.breakdown_type == "cohort"
            and isinstance(self.query.breakdownFilter.breakdown, list)
            and len(self.query.breakdownFilter.breakdown) > 1
            and not any(value == "all" for value in self.query.breakdownFilter.breakdown)
        ):
            self.modifiers.inCohortVia = InCohortVia.leftjoin_conjoined

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
            self.modifiers.inCohortVia != InCohortVia.leftjoin_conjoined
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

        if self.query.trendsFilter is not None and self.query.trendsFilter.compare:
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
        has_compare = bool(self.query.trendsFilter and self.query.trendsFilter.compare)
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
            and self.modifiers.inCohortVia != InCohortVia.leftjoin_conjoined
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
                                "breakdown_value": any_result.get("breakdown_value"),
                                "compare_label": any_result.get("compare_label"),
                                "days": any_result.get("days"),
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
            display = ChartDisplayType.ActionsLineGraph
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
            self.query.trendsFilter is not None
            and self.query.trendsFilter.compare
            and dashboard_filter.date_from == "all"
        ):
            # TODO: Move this "All time" range handling out of `apply_dashboard_filters` – if the date range is "all",
            # we should disable `compare` _no matter how_ we arrived at the final executed query
            self.query.trendsFilter.compare = False
