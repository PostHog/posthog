from copy import deepcopy
from datetime import timedelta
from itertools import groupby
from math import ceil
from operator import itemgetter
import threading
from typing import List, Optional, Any, Dict
from dateutil import parser
from dateutil.relativedelta import relativedelta
from django.conf import settings

from django.utils.timezone import datetime
from posthog.caching.insights_api import (
    BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL,
    REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL,
)
from posthog.caching.utils import is_stale

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.breakdown_values import (
    BREAKDOWN_NULL_NUMERIC_LABEL,
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_NUMERIC_LABEL,
    BREAKDOWN_OTHER_STRING_LABEL,
)
from posthog.hogql_queries.insights.trends.display import TrendsDisplay
from posthog.hogql_queries.insights.trends.query_builder import TrendsQueryBuilder
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
from posthog.schema import (
    ActionsNode,
    BreakdownItem,
    ChartDisplayType,
    Compare,
    CompareItem,
    DayItem,
    EventsNode,
    HogQLQueryResponse,
    InCohortVia,
    InsightActorsQueryOptionsResponse,
    QueryTiming,
    Series,
    TrendsQuery,
    TrendsQueryResponse,
    HogQLQueryModifiers,
)
from posthog.utils import format_label_date


class TrendsQueryRunner(QueryRunner):
    query: TrendsQuery
    query_type = TrendsQuery
    series: List[SeriesWithExtras]

    def __init__(
        self,
        query: TrendsQuery | Dict[str, Any],
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

        refresh_frequency = BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
        if interval == "hour" or (delta_days is not None and delta_days <= 7):
            # The interval is shorter for short-term insights
            refresh_frequency = REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL

        return refresh_frequency

    def to_query(self) -> ast.SelectUnionQuery:
        queries = []
        for query in self.to_queries():
            if isinstance(query, ast.SelectQuery):
                queries.append(query)
            else:
                queries.extend(query.select_queries)
        return ast.SelectUnionQuery(select_queries=queries)

    def to_queries(self) -> List[ast.SelectQuery | ast.SelectUnionQuery]:
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
                )
                queries.append(query_builder.build_query())

        return queries

    def to_actors_query(
        self,
        time_frame: Optional[str | int],
        series_index: int,
        breakdown_value: Optional[str | int] = None,
        compare: Optional[Compare] = None,
    ) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("trends_to_actors_query"):
            series = self.query.series[series_index]

            if compare == Compare.previous:
                query_date_range = self.query_previous_date_range

                delta_mappings = self.query_previous_date_range.date_from_delta_mappings()
                if delta_mappings is not None and time_frame is not None and isinstance(time_frame, str):
                    relative_delta = relativedelta(**delta_mappings)
                    parsed_dt = parser.isoparse(time_frame)
                    parse_dt_with_relative_delta = parsed_dt - relative_delta
                    time_frame = parse_dt_with_relative_delta.strftime("%Y-%m-%d")
            else:
                query_date_range = self.query_date_range

            query_builder = TrendsQueryBuilder(
                trends_query=self.query,
                team=self.team,
                query_date_range=query_date_range,
                series=series,
                timings=self.timings,
                modifiers=self.modifiers,
            )

            query = query_builder.build_actors_query(time_frame=time_frame, breakdown_filter=breakdown_value)

        return query

    def to_actors_query_options(self) -> InsightActorsQueryOptionsResponse:
        res_breakdown: List[BreakdownItem] | None = None
        res_series: List[Series] = []
        res_compare: List[CompareItem] | None = None

        # Days
        res_days: List[DayItem] = [DayItem(label=day, value=day) for day in self.query_date_range.all_values()]

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
            )

            breakdown = query_builder._breakdown(is_actors_query=False)
            if not breakdown.enabled:
                break

            is_boolean_breakdown = self._is_breakdown_field_boolean()
            is_histogram_breakdown = breakdown.is_histogram_breakdown
            breakdown_values: List[str | int]
            res_breakdown = []

            if is_histogram_breakdown:
                buckets = breakdown._get_breakdown_histogram_buckets()
                breakdown_values = [f"[{t[0]},{t[1]}]" for t in buckets]
                breakdown_values.append('["",""]')
            else:
                breakdown_values = breakdown._get_breakdown_values

            for value in breakdown_values:
                if self.query.breakdownFilter is not None and self.query.breakdownFilter.breakdown_type == "cohort":
                    cohort_name = "all users" if str(value) == "0" else Cohort.objects.get(pk=value).name
                    label = cohort_name
                    value = value
                elif value == BREAKDOWN_OTHER_STRING_LABEL or value == BREAKDOWN_OTHER_NUMERIC_LABEL:
                    # label = "Other"
                    # value = BREAKDOWN_OTHER_STRING_LABEL
                    continue  # TODO: Add support for "other" breakdowns
                elif value == BREAKDOWN_NULL_STRING_LABEL or value == BREAKDOWN_NULL_NUMERIC_LABEL:
                    # label = "Null"
                    # value = BREAKDOWN_NULL_STRING_LABEL
                    continue  # TODO: Add support for "null" breakdowns
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

        res_matrix: List[List[Any] | Any | None] = [None] * len(queries)
        timings_matrix: List[List[QueryTiming] | None] = [None] * len(queries)
        errors: List[Exception] = []

        def run(index: int, query: ast.SelectQuery | ast.SelectUnionQuery, is_parallel: bool):
            try:
                series_with_extra = self.series[index]

                response = execute_hogql_query(
                    query_type="TrendsQuery",
                    query=query,
                    team=self.team,
                    timings=self.timings,
                    modifiers=self.modifiers,
                )

                timings_matrix[index] = response.timings
                res_matrix[index] = self.build_series_response(response, series_with_extra, len(queries))
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
        res = []
        for result in res_matrix:
            if isinstance(result, List):
                res.extend(result)
            else:
                res.append(result)

        timings = []
        for result in timings_matrix:
            if isinstance(result, List):
                timings.extend(result)
            else:
                timings.append(result)

        if (
            self.query.trendsFilter is not None
            and self.query.trendsFilter.formula is not None
            and self.query.trendsFilter.formula != ""
        ):
            with self.timings.measure("apply_formula"):
                res = self.apply_formula(self.query.trendsFilter.formula, res)

        return TrendsQueryResponse(results=res, timings=timings, hogql=response_hogql)

    def build_series_response(self, response: HogQLQueryResponse, series: SeriesWithExtras, series_count: int):
        if response.results is None:
            return []

        def get_value(name: str, val: Any):
            if name not in ["date", "total", "breakdown_value"]:
                raise Exception("Column not found in hogql results")
            if response.columns is None:
                raise Exception("No columns returned from hogql results")

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
                    "days": [
                        item.strftime(
                            "%Y-%m-%d{}".format(" %H:%M:%S" if self.query_date_range.interval_name == "hour" else "")
                        )
                        for item in get_value("date", val)
                    ]
                    if response.columns and "date" in response.columns
                    else [],
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
                        "custom_name": None,
                        "math": series.series.math,
                        "math_property": None,
                        "math_hogql": None,
                        "math_group_type_index": None,
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
                            "%Y-%m-%d{}".format(" %H:%M:%S" if self.query_date_range.interval_name == "hour" else "")
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
                        "custom_name": None,
                        "math": series.series.math,
                        "math_property": None,
                        "math_hogql": None,
                        "math_group_type_index": None,
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

                # If the breakdown value is the numeric "other", then set it to the string version
                if (
                    remapped_label == BREAKDOWN_OTHER_NUMERIC_LABEL
                    or remapped_label == str(BREAKDOWN_OTHER_NUMERIC_LABEL)
                    or remapped_label == float(BREAKDOWN_OTHER_NUMERIC_LABEL)
                ):
                    series_object["breakdown_value"] = BREAKDOWN_OTHER_STRING_LABEL
                    if real_series_count > 1 or self._is_breakdown_field_boolean():
                        series_object["label"] = "{} - {}".format(series_label or "All events", "Other")
                    else:
                        series_object["label"] = "Other"

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

    def series_event(self, series: EventsNode | ActionsNode) -> str | None:
        if isinstance(series, EventsNode):
            return series.event
        if isinstance(series, ActionsNode):
            # TODO: Can we load the Action in more efficiently?
            action = Action.objects.get(pk=int(series.id), team=self.team)
            return action.name
        return None

    def update_hogql_modifiers(self) -> None:
        if (
            self.modifiers.inCohortVia == InCohortVia.auto
            and self.query.breakdownFilter is not None
            and self.query.breakdownFilter.breakdown_type == "cohort"
            and isinstance(self.query.breakdownFilter.breakdown, List)
            and len(self.query.breakdownFilter.breakdown) > 1
            and not any(value == "all" for value in self.query.breakdownFilter.breakdown)
        ):
            self.modifiers.inCohortVia = InCohortVia.leftjoin_conjoined

    def setup_series(self) -> List[SeriesWithExtras]:
        series_with_extras = [
            SeriesWithExtras(
                series=series,
                series_order=index,
                is_previous_period_series=None,
                overriden_query=None,
                aggregate_values=self._trends_display.should_aggregate_values(),
            )
            for index, series in enumerate(self.query.series)
        ]

        if (
            self.modifiers.inCohortVia != InCohortVia.leftjoin_conjoined
            and self.query.breakdownFilter is not None
            and self.query.breakdownFilter.breakdown_type == "cohort"
        ):
            updated_series = []
            if isinstance(self.query.breakdownFilter.breakdown, List):
                cohort_ids = self.query.breakdownFilter.breakdown
            else:
                cohort_ids = [self.query.breakdownFilter.breakdown]

            for cohort_id in cohort_ids:
                for series in series_with_extras:
                    copied_query = deepcopy(self.query)
                    copied_query.breakdownFilter.breakdown = cohort_id

                    updated_series.append(
                        SeriesWithExtras(
                            series=series.series,
                            series_order=series.series_order,
                            is_previous_period_series=series.is_previous_period_series,
                            overriden_query=copied_query,
                            aggregate_values=self._trends_display.should_aggregate_values(),
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
                        aggregate_values=self._trends_display.should_aggregate_values(),
                    )
                )
                updated_series.append(
                    SeriesWithExtras(
                        series=series.series,
                        series_order=series.series_order,
                        is_previous_period_series=True,
                        overriden_query=series.overriden_query,
                        aggregate_values=self._trends_display.should_aggregate_values(),
                    )
                )
            series_with_extras = updated_series

        return series_with_extras

    def apply_formula(self, formula: str, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if self.query.trendsFilter is not None and self.query.trendsFilter.compare:
            sorted_results = sorted(results, key=itemgetter("compare_label"))
            res = []
            for _, group in groupby(sorted_results, key=itemgetter("compare_label")):
                group_list = list(group)

                if self._trends_display.should_aggregate_values():
                    series_data = list(map(lambda s: [s["aggregated_value"]], group_list))
                    new_series_data = FormulaAST(series_data).call(formula)

                    new_result = group_list[0]
                    new_result["aggregated_value"] = float(sum(new_series_data))
                    new_result["data"] = None
                    new_result["count"] = 0
                    new_result["label"] = f"Formula ({formula})"
                    res.append(new_result)
                else:
                    series_data = list(map(lambda s: s["data"], group_list))
                    new_series_data = FormulaAST(series_data).call(formula)

                    new_result = group_list[0]
                    new_result["data"] = new_series_data
                    new_result["count"] = float(sum(new_series_data))
                    new_result["label"] = f"Formula ({formula})"
                    res.append(new_result)
            return res

        if self._trends_display.should_aggregate_values():
            series_data = list(map(lambda s: [s["aggregated_value"]], results))
            new_series_data = FormulaAST(series_data).call(formula)

            new_result = results[0]
            new_result["aggregated_value"] = float(sum(new_series_data))
            new_result["data"] = None
            new_result["count"] = 0
            new_result["label"] = f"Formula ({formula})"
        else:
            series_data = list(map(lambda s: s["data"], results))
            new_series_data = FormulaAST(series_data).call(formula)

            new_result = results[0]
            new_result["data"] = new_series_data
            new_result["count"] = float(sum(new_series_data))
            new_result["label"] = f"Formula ({formula})"

        return [new_result]

    def _is_breakdown_field_boolean(self):
        if not self.query.breakdownFilter or not self.query.breakdownFilter.breakdown_type:
            return False

        if (
            self.query.breakdownFilter.breakdown_type == "hogql"
            or self.query.breakdownFilter.breakdown_type == "cohort"
            or self.query.breakdownFilter.breakdown_type == "session"
        ):
            return False

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
    ):
        return PropertyDefinition.objects.get(
            name=field,
            team=self.team,
            type=field_type,
            group_type_index=group_type_index if field_type == PropertyDefinition.Type.GROUP else None,
        ).property_type

    # TODO: Move this to posthog/hogql_queries/legacy_compatibility/query_to_filter.py
    def _query_to_filter(self) -> Dict[str, Any]:
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
