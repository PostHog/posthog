from copy import deepcopy
from datetime import timedelta
from itertools import groupby
from math import ceil
from operator import itemgetter
from typing import List, Optional, Any, Dict

from django.utils.timezone import datetime
from posthog.caching.insights_api import (
    BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL,
    REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL,
)
from posthog.caching.utils import is_stale

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.query_builder import TrendsQueryBuilder
from posthog.hogql_queries.insights.trends.series_with_extras import SeriesWithExtras
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.formula_ast import FormulaAST
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import (
    QueryPreviousPeriodDateRange,
)
from posthog.models import Team
from posthog.models.cohort.cohort import Cohort
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property_definition import PropertyDefinition
from posthog.schema import (
    ActionsNode,
    EventsNode,
    HogQLQueryResponse,
    TrendsQuery,
    TrendsQueryResponse,
)


class TrendsQueryRunner(QueryRunner):
    query: TrendsQuery
    query_type = TrendsQuery
    series: List[SeriesWithExtras]

    def __init__(
        self,
        query: TrendsQuery | Dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        in_export_context: Optional[int] = None,
    ):
        super().__init__(query, team, timings, in_export_context)
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

    def to_query(self) -> List[ast.SelectQuery]:
        queries = []
        with self.timings.measure("trends_query"):
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
                )
                queries.append(query_builder.build_query())

        return queries

    def calculate(self):
        queries = self.to_query()

        res = []
        timings = []

        for index, query in enumerate(queries):
            series_with_extra = self.series[index]

            response = execute_hogql_query(
                query_type="TrendsQuery",
                query=query,
                team=self.team,
                timings=self.timings,
            )

            timings.extend(response.timings)

            res.extend(self.build_series_response(response, series_with_extra))

        if (
            self.query.trendsFilter is not None
            and self.query.trendsFilter.formula is not None
            and self.query.trendsFilter.formula != ""
        ):
            res = self.apply_formula(self.query.trendsFilter.formula, res)

        return TrendsQueryResponse(results=res, timings=timings)

    def build_series_response(self, response: HogQLQueryResponse, series: SeriesWithExtras):
        if response.results is None:
            return []

        res = []
        for val in response.results:
            series_object = {
                "data": val[1],
                "labels": [item.strftime("%-d-%b-%Y") for item in val[0]],  # TODO: Add back in hour formatting
                "days": [item.strftime("%Y-%m-%d") for item in val[0]],  # TODO: Add back in hour formatting
                "count": float(sum(val[1])),
                "label": "All events" if self.series_event(series.series) is None else self.series_event(series.series),
                "filter": self._query_to_filter(),
                "action": {  # TODO: Populate missing props in `action`
                    "id": self.series_event(series.series),
                    "type": "events",
                    "order": 0,
                    "name": self.series_event(series.series) or "All events",
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
                    for i in range(len(series_object["labels"]))
                ]

                series_object["compare"] = True
                series_object["compare_label"] = "previous" if series.is_previous_period_series else "current"
                series_object["labels"] = labels

            # Modifications for when breakdowns are active
            if self.query.breakdown is not None and self.query.breakdown.breakdown is not None:
                if self._is_breakdown_field_boolean():
                    remapped_label = self._convert_boolean(val[2])
                    series_object["label"] = "{} - {}".format(series_object["label"], remapped_label)
                    series_object["breakdown_value"] = remapped_label
                elif self.query.breakdown.breakdown_type == "cohort":
                    cohort_id = val[2]
                    cohort_name = Cohort.objects.get(pk=cohort_id).name

                    series_object["label"] = "{} - {}".format(series_object["label"], cohort_name)
                    series_object["breakdown_value"] = val[2]
                else:
                    series_object["label"] = "{} - {}".format(series_object["label"], val[2])
                    series_object["breakdown_value"] = val[2]

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
        return None

    def setup_series(self) -> List[SeriesWithExtras]:
        series_with_extras = [SeriesWithExtras(series, None, None) for series in self.query.series]

        if self.query.breakdown is not None and self.query.breakdown.breakdown_type == "cohort":
            updated_series = []
            for cohort_id in self.query.breakdown.breakdown:
                for series in series_with_extras:
                    copied_query = deepcopy(self.query)
                    copied_query.breakdown.breakdown = cohort_id

                    updated_series.append(
                        SeriesWithExtras(
                            series=series.series,
                            is_previous_period_series=series.is_previous_period_series,
                            overriden_query=copied_query,
                        )
                    )
            series_with_extras = updated_series

        if self.query.trendsFilter is not None and self.query.trendsFilter.compare:
            updated_series = []
            for series in series_with_extras:
                updated_series.append(
                    SeriesWithExtras(
                        series=series.series,
                        is_previous_period_series=False,
                        overriden_query=series.overriden_query,
                    )
                )
                updated_series.append(
                    SeriesWithExtras(
                        series=series.series,
                        is_previous_period_series=True,
                        overriden_query=series.overriden_query,
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

                series_data = map(lambda s: s["data"], group_list)
                new_series_data = FormulaAST(series_data).call(formula)

                new_result = group_list[0]
                new_result["data"] = new_series_data
                new_result["count"] = float(sum(new_series_data))
                new_result["label"] = f"Formula ({formula})"

                res.append(new_result)
            return res

        series_data = map(lambda s: s["data"], results)
        new_series_data = FormulaAST(series_data).call(formula)
        new_result = results[0]

        new_result["data"] = new_series_data
        new_result["count"] = float(sum(new_series_data))
        new_result["label"] = f"Formula ({formula})"

        return [new_result]

    def _is_breakdown_field_boolean(self):
        if (
            self.query.breakdown.breakdown_type == "hogql"
            or self.query.breakdown.breakdown_type == "cohort"
            or self.query.breakdown.breakdown_type == "session"
        ):
            return False

        if self.query.breakdown.breakdown_type == "person":
            property_type = PropertyDefinition.Type.PERSON
        elif self.query.breakdown.breakdown_type == "group":
            property_type = PropertyDefinition.Type.GROUP
        else:
            property_type = PropertyDefinition.Type.EVENT

        field_type = self._event_property(
            self.query.breakdown.breakdown,
            property_type,
            self.query.breakdown.breakdown_group_type_index,
        )
        return field_type == "Boolean"

    def _convert_boolean(self, value: any):
        bool_map = {1: "true", 0: "false", "": ""}
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

    def _query_to_filter(self) -> Dict[str, any]:
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

        if self.query.breakdown is not None:
            filter_dict.update(**self.query.breakdown.__dict__)

        return {k: v for k, v in filter_dict.items() if v is not None}
