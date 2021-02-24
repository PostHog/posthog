from abc import abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from django.db.models.manager import BaseManager
from django.utils import timezone

from ee.clickhouse.client import substitute_params, sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.trends.util import parse_response, process_math
from ee.clickhouse.queries.util import date_from_clause, get_time_diff, get_trunc_func_ch, parse_timestamps
from ee.clickhouse.sql.events import EVENT_JOIN_PERSON_SQL, NULL_BREAKDOWN_SQL, NULL_SQL
from ee.clickhouse.sql.person import GET_LATEST_PERSON_SQL
from ee.clickhouse.sql.trends.breakdown import (
    BREAKDOWN_AGGREGATE_DEFAULT_SQL,
    BREAKDOWN_AGGREGATE_QUERY_SQL,
    BREAKDOWN_COHORT_JOIN_SQL,
    BREAKDOWN_CONDITIONS_SQL,
    BREAKDOWN_DEFAULT_SQL,
    BREAKDOWN_PERSON_PROP_JOIN_SQL,
    BREAKDOWN_PROP_JOIN_SQL,
    BREAKDOWN_QUERY_SQL,
)
from ee.clickhouse.sql.trends.top_elements import TOP_ELEMENTS_ARRAY_OF_KEY_SQL
from ee.clickhouse.sql.trends.top_person_props import TOP_PERSON_PROPS_ARRAY_OF_KEY_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TRENDS_PIE, TRENDS_TABLE
from posthog.models.action import Action
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
        for idx, stats in enumerate(result):
            additional_values = self.breakdown_result_descriptors(stats[1], self.filter, self.entity)
            parsed_result = {"aggregated_value": stats[0], **additional_values}
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


class BreakdownFilterConstructor:
    breakdown_value = "value"

    @staticmethod
    def for_entity(entity: Entity, filter: Filter, team_id: int, round_interval: bool) -> "BreakdownFilterConstructor":
        if filter.breakdown_type == "cohort":
            return CohortBreakdownFilterConstructor(entity, filter, team_id, round_interval)
        elif filter.breakdown_type == "person":
            return PersonBreakdownFilterConstructor(entity, filter, team_id, round_interval)
        else:
            return PropertyBreakdownFilterConstructor(entity, filter, team_id, round_interval)

    def __init__(self, entity: Entity, filter: Filter, team_id: int, round_interval: bool):
        self.entity = entity
        self.filter = filter
        self.team_id = team_id
        self.round_interval = round_interval

    def action_query_params(self):
        if self.entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=self.entity.id)
            return format_action_filter(action)
        else:
            return "", {}

    def base_query_arguments(self):
        interval_annotation = get_trunc_func_ch(self.filter.interval)
        _, parsed_date_to, date_params = parse_timestamps(filter=self.filter, team_id=self.team_id)
        action_query, action_params = self.action_query_params()

        props_to_filter = [*self.filter.properties, *self.entity.properties]
        prop_filters, prop_filter_params = parse_prop_clauses(props_to_filter, self.team_id, table_name="e")

        formatting_params = {
            "parsed_date_from": date_from_clause(interval_annotation, self.round_interval),
            "parsed_date_to": parsed_date_to,
            "actions_query": "AND {}".format(action_query) if action_query else "",
            "event_filter": "AND event = %(event)s" if not action_query else "",
            "filters": prop_filters if props_to_filter else "",
        }

        query_params = {
            **prop_filter_params,
            **action_params,
            **date_params,
        }

        return formatting_params, query_params

    @property
    def query(self):
        return self.built_query[0]

    @property
    def query_params(self):
        _, params = self.base_query_arguments()
        return {**self.built_query[1], **params}

    @cached_property
    def built_query(self):
        return self.build_query()

    @abstractmethod
    def build_query(self):
        pass


class CohortBreakdownFilterConstructor(BreakdownFilterConstructor):
    def build_query(self):
        cohort_queries, cohort_ids, cohort_params = self._format_breakdown_cohort_join_query()

        formatting_params, _ = self.base_query_arguments()
        return (
            BREAKDOWN_COHORT_JOIN_SQL.format(cohort_queries=cohort_queries, **formatting_params),
            {"values": cohort_ids, **cohort_params},
        )

    def _format_breakdown_cohort_join_query(self) -> Tuple[str, List, Dict]:
        cohorts = Cohort.objects.filter(team_id=self.team_id, pk__in=[b for b in self.filter.breakdown if b != "all"])
        cohort_queries, params = self._parse_breakdown_cohorts(cohorts)
        ids = [cohort.pk for cohort in cohorts]
        if "all" in self.filter.breakdown:
            all_query, all_params = self._format_all_query()
            cohort_queries.append(all_query)
            params = {**params, **all_params}
            ids.append(0)
        return " UNION ALL ".join(cohort_queries), ids, params

    def _parse_breakdown_cohorts(self, cohorts: BaseManager) -> Tuple[List[str], Dict]:
        queries = []
        params: Dict[str, Any] = {}
        for cohort in cohorts:
            person_id_query, cohort_filter_params = format_filter_query(cohort)
            params = {**params, **cohort_filter_params}
            cohort_query = person_id_query.replace(
                "SELECT distinct_id", "SELECT distinct_id, {} as value".format(cohort.pk)
            )
            queries.append(cohort_query)
        return queries, params

    def _format_all_query(self) -> Tuple[str, Dict]:
        parsed_date_from, parsed_date_to, date_params = parse_timestamps(
            filter=self.filter, team_id=self.team_id, table="all_events."
        )

        props_to_filter = [*self.filter.properties, *self.entity.properties]
        prop_filters, prop_filter_params = parse_prop_clauses(
            props_to_filter, self.team_id, prepend="all_cohort_", table_name="all_events"
        )
        query = """
            SELECT DISTINCT distinct_id, 0 as value
            FROM events all_events
            WHERE team_id = {} {} {} {}
            """.format(
            self.team_id, parsed_date_from, parsed_date_to, prop_filters
        )
        return query, {**date_params, **prop_filter_params}


class PersonBreakdownFilterConstructor(BreakdownFilterConstructor):
    def build_query(self):
        parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=self.filter, team_id=self.team_id)

        elements_query = TOP_PERSON_PROPS_ARRAY_OF_KEY_SQL.format(
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            latest_person_sql=GET_LATEST_PERSON_SQL.format(query=""),
        )
        top_elements_array = _get_top_elements(elements_query, self.filter, self.team_id)
        formatting_params, _ = self.base_query_arguments()
        return (
            BREAKDOWN_PERSON_PROP_JOIN_SQL.format(
                latest_person_sql=GET_LATEST_PERSON_SQL.format(query=""), **formatting_params
            ),
            {"values": top_elements_array},
        )


class PropertyBreakdownFilterConstructor(BreakdownFilterConstructor):
    breakdown_value = "JSONExtractRaw(properties, %(key)s)"

    def build_query(self):
        parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=self.filter, team_id=self.team_id)
        elements_query = TOP_ELEMENTS_ARRAY_OF_KEY_SQL.format(
            parsed_date_from=parsed_date_from, parsed_date_to=parsed_date_to
        )

        top_elements_array = _get_top_elements(elements_query, self.filter, self.team_id)
        formatting_params, _ = self.base_query_arguments()
        return BREAKDOWN_PROP_JOIN_SQL.format(**formatting_params), {"values": top_elements_array}


def _get_top_elements(query: str, filter: Filter, team_id: int) -> List:
    element_params = {"key": filter.breakdown, "limit": 20, "team_id": team_id}

    try:
        top_elements_array_result = sync_execute(query, element_params)
        top_elements_array = top_elements_array_result[0][0]
    except:
        top_elements_array = []

    return top_elements_array
