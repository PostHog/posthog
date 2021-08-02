from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.breakdown_props import (
    format_breakdown_cohort_join_query,
    get_breakdown_event_prop_values,
    get_breakdown_person_prop_values,
)
from ee.clickhouse.queries.trends.util import enumerate_time_range, get_active_user_params, parse_response, process_math
from ee.clickhouse.queries.util import date_from_clause, get_time_diff, get_trunc_func_ch, parse_timestamps
from ee.clickhouse.sql.events import EVENT_JOIN_PERSON_SQL
from ee.clickhouse.sql.person import GET_LATEST_PERSON_SQL, GET_TEAM_PERSON_DISTINCT_IDS
from ee.clickhouse.sql.trends.breakdown import (
    BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL,
    BREAKDOWN_ACTIVE_USER_INNER_SQL,
    BREAKDOWN_AGGREGATE_QUERY_SQL,
    BREAKDOWN_COHORT_JOIN_SQL,
    BREAKDOWN_INNER_SQL,
    BREAKDOWN_PERSON_PROP_JOIN_SQL,
    BREAKDOWN_PROP_JOIN_SQL,
    BREAKDOWN_QUERY_SQL,
    NONE_BREAKDOWN_PERSON_PROP_JOIN_SQL,
    NONE_BREAKDOWN_PROP_JOIN_SQL,
)
from posthog.constants import MONTHLY_ACTIVE, TREND_FILTER_TYPE_ACTIONS, TRENDS_DISPLAY_BY_VALUE, WEEKLY_ACTIVE
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters import Filter


class ClickhouseTrendsBreakdown:
    def _format_breakdown_query(self, entity: Entity, filter: Filter, team_id: int) -> Tuple[str, Dict, Callable]:
        # process params
        params: Dict[str, Any] = {"team_id": team_id}
        interval_annotation = get_trunc_func_ch(filter.interval)
        num_intervals, seconds_in_interval, round_interval = get_time_diff(
            filter.interval or "day", filter.date_from, filter.date_to, team_id
        )
        _, parsed_date_to, date_params = parse_timestamps(filter=filter, team_id=team_id)

        props_to_filter = [*filter.properties, *entity.properties]
        prop_filters, prop_filter_params = parse_prop_clauses(
            props_to_filter, team_id, table_name="e", filter_test_accounts=filter.filter_test_accounts
        )
        aggregate_operation, _, math_params = process_math(entity)

        if entity.math == "dau" or filter.breakdown_type == "person":
            join_condition = EVENT_JOIN_PERSON_SQL
        else:
            join_condition = ""

        action_query = ""
        action_params: Dict = {}
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = entity.get_action()
            action_query, action_params = format_action_filter(action, table_name="e")

        params = {
            **params,
            **math_params,
            **prop_filter_params,
            **action_params,
            "event": entity.id,
            "key": filter.breakdown,
            **date_params,
        }

        breakdown_filter_params = {
            "parsed_date_from": date_from_clause(interval_annotation, round_interval),
            "parsed_date_to": parsed_date_to,
            "actions_query": "AND {}".format(action_query) if action_query else "",
            "event_filter": "AND event = %(event)s" if not action_query else "",
            "filters": prop_filters if props_to_filter else "",
        }

        _params, _breakdown_filter_params, none_join, none_union = {}, {}, None, None

        if filter.breakdown_type == "cohort":
            _params, breakdown_filter, _breakdown_filter_params, breakdown_value = self._breakdown_cohort_params(
                team_id, filter, entity
            )
        elif filter.breakdown_type == "person":
            (
                _params,
                breakdown_filter,
                _breakdown_filter_params,
                breakdown_value,
                none_join,
            ) = self._breakdown_person_params(
                "count(*)" if entity.math == "dau" else aggregate_operation, entity, filter, team_id
            )
        else:
            (
                _params,
                breakdown_filter,
                _breakdown_filter_params,
                breakdown_value,
                none_join,
            ) = self._breakdown_prop_params(
                "count(*)" if entity.math == "dau" else aggregate_operation, entity, filter, team_id
            )

        if len(_params["values"]) == 0:
            return "SELECT 1", {}, lambda _: []

        params = {**params, **_params}
        breakdown_filter_params = {**breakdown_filter_params, **_breakdown_filter_params}

        if filter.display in TRENDS_DISPLAY_BY_VALUE:
            breakdown_filter = breakdown_filter.format(**breakdown_filter_params)
            content_sql = BREAKDOWN_AGGREGATE_QUERY_SQL.format(
                breakdown_filter=breakdown_filter,
                event_join=join_condition,
                aggregate_operation=aggregate_operation,
                breakdown_value=breakdown_value,
            )
            time_range = enumerate_time_range(filter, seconds_in_interval)

            return content_sql, params, self._parse_single_aggregate_result(filter, entity, {"days": time_range})

        else:

            breakdown_filter = breakdown_filter.format(**breakdown_filter_params)
            none_join = none_join.format(**breakdown_filter_params) if none_join else None

            if entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
                active_user_params = get_active_user_params(filter, entity, team_id)
                conditions = BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL.format(
                    **breakdown_filter_params, **active_user_params
                )
                inner_sql = BREAKDOWN_ACTIVE_USER_INNER_SQL.format(
                    breakdown_filter=breakdown_filter,
                    event_join=join_condition,
                    aggregate_operation=aggregate_operation,
                    interval_annotation=interval_annotation,
                    breakdown_value=breakdown_value,
                    conditions=conditions,
                    GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
                    **active_user_params,
                    **breakdown_filter_params
                )
            else:
                inner_sql = BREAKDOWN_INNER_SQL.format(
                    breakdown_filter=breakdown_filter,
                    event_join=join_condition,
                    aggregate_operation=aggregate_operation,
                    interval_annotation=interval_annotation,
                    breakdown_value=breakdown_value,
                )
                if none_join:
                    none_union = "UNION ALL " + BREAKDOWN_INNER_SQL.format(
                        breakdown_filter=none_join,
                        event_join=join_condition,
                        aggregate_operation=aggregate_operation,
                        interval_annotation=interval_annotation,
                        breakdown_value="'none'",
                    )

            breakdown_query = BREAKDOWN_QUERY_SQL.format(
                interval=interval_annotation,
                num_intervals=num_intervals,
                inner_sql=inner_sql,
                none_union=none_union if none_union else "",
            )
            params.update(
                {
                    "date_to": filter.date_to.strftime("%Y-%m-%d %H:%M:%S"),
                    "seconds_in_interval": seconds_in_interval,
                    "num_intervals": num_intervals,
                }
            )

            return breakdown_query, params, self._parse_trend_result(filter, entity)

    def _breakdown_cohort_params(self, team_id: int, filter: Filter, entity: Entity):
        cohort_queries, cohort_ids, cohort_params = format_breakdown_cohort_join_query(team_id, filter, entity=entity)
        params = {"values": cohort_ids, **cohort_params}
        breakdown_filter = BREAKDOWN_COHORT_JOIN_SQL
        breakdown_filter_params = {"cohort_queries": cohort_queries}

        return params, breakdown_filter, breakdown_filter_params, "value"

    def _breakdown_person_params(self, aggregate_operation: str, entity: Entity, filter: Filter, team_id: int):
        values_arr = get_breakdown_person_prop_values(filter, entity, aggregate_operation, team_id)
        breakdown_filter_params = {
            "latest_person_sql": GET_LATEST_PERSON_SQL.format(query=""),
        }
        params = {
            "values": [*values_arr, "none"],
        }

        return (
            params,
            BREAKDOWN_PERSON_PROP_JOIN_SQL,
            breakdown_filter_params,
            "value",
            None if filter.offset else NONE_BREAKDOWN_PERSON_PROP_JOIN_SQL,
        )

    def _breakdown_prop_params(self, aggregate_operation: str, entity: Entity, filter: Filter, team_id: int):
        values_arr = get_breakdown_event_prop_values(filter, entity, aggregate_operation, team_id)
        params = {
            "values": [*values_arr, "none"],
        }
        return (
            params,
            BREAKDOWN_PROP_JOIN_SQL,
            {},
            "trim(BOTH '\"' FROM JSONExtractRaw(properties, %(key)s))",
            None if filter.offset else NONE_BREAKDOWN_PROP_JOIN_SQL,
        )

    def _parse_single_aggregate_result(
        self, filter: Filter, entity: Entity, additional_values: Dict[str, Any]
    ) -> Callable:
        def _parse(result: List) -> List:
            parsed_results = []
            for idx, stats in enumerate(result):
                result_descriptors = self._breakdown_result_descriptors(stats[1], filter, entity)
                parsed_result = {"aggregated_value": stats[0], **result_descriptors, **additional_values}
                parsed_results.append(parsed_result)

            return parsed_results

        return _parse

    def _parse_trend_result(self, filter: Filter, entity: Entity) -> Callable:
        def _parse(result: List) -> List:
            parsed_results = []
            for idx, stats in enumerate(result):
                result_descriptors = self._breakdown_result_descriptors(stats[2], filter, entity)
                parsed_result = parse_response(stats, filter, result_descriptors)
                parsed_results.append(parsed_result)

            return sorted(parsed_results, key=lambda x: 0 if x.get("breakdown_value") != "all" else 1)

        return _parse

    def _breakdown_result_descriptors(self, breakdown_value, filter: Filter, entity: Entity):
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

    def _get_top_elements(self, query: str, filter: Filter, team_id: int, params: Dict = {}) -> List:
        # use limit of 25 to determine if there are more than 20
        element_params = {"key": filter.breakdown, "limit": 25, "team_id": team_id, "offset": filter.offset, **params}

        try:
            top_elements_array_result = sync_execute(query, element_params)
            top_elements_array = top_elements_array_result[0][0]
        except:
            top_elements_array = []

        return top_elements_array
