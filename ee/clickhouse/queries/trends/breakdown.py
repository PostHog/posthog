from abc import abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union

from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.trends.breakdown_filter_constructor import BreakdownFilterConstructor
from ee.clickhouse.queries.trends.util import parse_response, process_math
from ee.clickhouse.queries.util import get_time_diff, get_trunc_func_ch
from ee.clickhouse.sql.events import EVENT_JOIN_PERSON_SQL, NULL_BREAKDOWN_SQL
from ee.clickhouse.sql.trends.breakdown import BREAKDOWN_AGGREGATE_QUERY_SQL, BREAKDOWN_QUERY_SQL
from posthog.constants import TRENDS_PIE, TRENDS_TABLE
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.filters.mixins.utils import cached_property


class ClickhouseTrendsBreakdown:
    @staticmethod
    def for_type(entity: Entity, filter: Filter, team_id: int) -> "ClickhouseTrendsBreakdown":
        if filter.display == TRENDS_TABLE or filter.display == TRENDS_PIE:
            return BreakdownAggregateTrends(entity, filter, team_id)
        else:
            return BreakdownSeriesTrends(entity, filter, team_id)

    def __init__(self, entity: Entity, filter: Filter, team_id: int):
        self.entity = entity
        self.filter = filter
        self.team_id = team_id
        self.interval_annotation = get_trunc_func_ch(self.filter.interval)

        self.num_intervals, self.seconds_in_interval, self.round_interval = get_time_diff(
            self.filter.interval or "day", self.filter.date_from, self.filter.date_to, self.team_id
        )
        self.aggregate_operation, _, self.math_params = process_math(self.entity)

    def run(self) -> List[Any]:
        if len(self.breakdown_filter.query_params["values"]) == 0:
            return []

        sql, params = self.format_query()
        return self.parse(sync_execute(sql, params))

    @abstractmethod
    def format_query(self) -> Tuple[str, Dict]:
        pass

    @abstractmethod
    def parse(self, result: List[Any]) -> List[Dict]:
        pass

    def join_condition(self):
        if self.entity.math == "dau" or self.filter.breakdown_type == "person":
            return EVENT_JOIN_PERSON_SQL
        else:
            return ""

    @cached_property
    def params(self):
        return {
            **self.math_params,
            **self.breakdown_filter.query_params,
            "team_id": self.team_id,
            "event": self.entity.id,
            "key": self.filter.breakdown,
        }

    @cached_property
    def breakdown_filter(self):
        return BreakdownFilterConstructor.for_entity(self.entity, self.filter, self.team_id, self.round_interval)

    def breakdown_result_descriptors(self, breakdown_value, filter: Filter, entity: Entity):
        stripped_value = breakdown_value.strip('"') if isinstance(breakdown_value, str) else breakdown_value

        extra_label = self._determine_breakdown_label(
            breakdown_value, filter.breakdown_type, filter.breakdown, stripped_value
        )
        label = "{} - {}".format(entity.name, extra_label)
        additional_values = {
            "label": label,
        }
        if filter.breakdown_type == "cohort":
            additional_values["breakdown_value"] = "all" if breakdown_value == 0 else breakdown_value
        else:
            additional_values["breakdown_value"] = stripped_value

        return additional_values

    def _determine_breakdown_label(
        self,
        breakdown_value: int,
        breakdown_type: Optional[str],
        breakdown: Union[str, List[Union[str, int]], None],
        value: Union[str, int],
    ) -> str:
        breakdown = breakdown if breakdown and isinstance(breakdown, list) else []
        if breakdown_type == "cohort":
            if breakdown_value == 0:
                return "all users"
            else:
                return Cohort.objects.get(pk=breakdown_value).name
        else:
            return str(value) or ""


class BreakdownAggregateTrends(ClickhouseTrendsBreakdown):
    def format_query(self) -> Tuple[str, Dict]:
        content_sql = BREAKDOWN_AGGREGATE_QUERY_SQL.format(
            breakdown_filter=self.breakdown_filter.query,
            event_join=self.join_condition(),
            aggregate_operation=self.aggregate_operation,
            breakdown_value=self.breakdown_filter.breakdown_value,
        )

        return content_sql, self.params

    def parse(self, result: List[Any]) -> List[Dict]:
        parsed_results = []
        for total, breakdown_value in result:
            additional_values = self.breakdown_result_descriptors(breakdown_value, self.filter, self.entity)
            parsed_result = {"aggregated_value": total, **additional_values}
            parsed_results.append(parsed_result)

        return parsed_results


class BreakdownSeriesTrends(ClickhouseTrendsBreakdown):
    def format_query(self) -> Tuple[str, Dict]:
        null_sql = NULL_BREAKDOWN_SQL.format(
            interval=self.interval_annotation,
            seconds_in_interval=self.seconds_in_interval,
            num_intervals=self.num_intervals,
            date_to=(self.filter.date_to).strftime("%Y-%m-%d %H:%M:%S"),
        )
        breakdown_query = BREAKDOWN_QUERY_SQL.format(
            null_sql=null_sql,
            breakdown_filter=self.breakdown_filter.query,
            event_join=self.join_condition(),
            aggregate_operation=self.aggregate_operation,
            interval_annotation=self.interval_annotation,
            breakdown_value=self.breakdown_filter.breakdown_value,
        )

        return breakdown_query, self.params

    def parse(self, result: List[Any]) -> List[Dict]:
        parsed_results = []
        for idx, stats in enumerate(result):
            additional_values = self.breakdown_result_descriptors(stats[2], self.filter, self.entity)
            parsed_result = parse_response(stats, self.filter, additional_values)
            parsed_results.append(parsed_result)

        return sorted(parsed_results, key=lambda x: 0 if x.get("breakdown_value") != "all" else 1)
