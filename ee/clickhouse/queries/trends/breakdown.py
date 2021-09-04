from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import get_property_string_expr, parse_prop_clauses
from ee.clickhouse.queries.breakdown_props import (
    ALL_USERS_COHORT_ID,
    format_breakdown_cohort_join_query,
    get_breakdown_cohort_name,
    get_breakdown_event_prop_values,
    get_breakdown_person_prop_values,
)
from ee.clickhouse.queries.column_optimizer import ColumnOptimizer
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from ee.clickhouse.queries.trends.util import enumerate_time_range, get_active_user_params, parse_response, process_math
from ee.clickhouse.queries.util import date_from_clause, get_time_diff, get_trunc_func_ch, parse_timestamps
from ee.clickhouse.sql.events import EVENT_JOIN_PERSON_SQL
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS
from ee.clickhouse.sql.trends.breakdown import (
    BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL,
    BREAKDOWN_ACTIVE_USER_INNER_SQL,
    BREAKDOWN_AGGREGATE_QUERY_SQL,
    BREAKDOWN_COHORT_JOIN_SQL,
    BREAKDOWN_INNER_SQL,
    BREAKDOWN_PERSON_PROP_JOIN_SQL,
    BREAKDOWN_PROP_JOIN_SQL,
    BREAKDOWN_QUERY_SQL,
)
from posthog.constants import MONTHLY_ACTIVE, TREND_FILTER_TYPE_ACTIONS, TRENDS_DISPLAY_BY_VALUE, WEEKLY_ACTIVE
from posthog.models.entity import Entity
from posthog.models.filters import Filter


class ClickhouseTrendsBreakdown:
    def __init__(
        self, entity: Entity, filter: Filter, team_id: int, column_optimizer: Optional[ColumnOptimizer] = None
    ):
        self.entity = entity
        self.filter = filter
        self.team_id = team_id
        self.params: Dict[str, Any] = {"team_id": team_id}
        self.column_optimizer = column_optimizer or ColumnOptimizer(self.filter, self.team_id)

    def get_query(self) -> Tuple[str, Dict, Callable]:
        interval_annotation = get_trunc_func_ch(self.filter.interval)
        num_intervals, seconds_in_interval, round_interval = get_time_diff(
            self.filter.interval, self.filter.date_from, self.filter.date_to, self.team_id
        )
        _, parsed_date_to, date_params = parse_timestamps(filter=self.filter, team_id=self.team_id)

        props_to_filter = [*self.filter.properties, *self.entity.properties]
        prop_filters, prop_filter_params = parse_prop_clauses(
            props_to_filter,
            self.team_id,
            table_name="e",
            filter_test_accounts=self.filter.filter_test_accounts,
            person_properties_column="person_props" if self.filter.breakdown_type == "person" else None,
        )
        aggregate_operation, _, math_params = process_math(self.entity)

        action_query = ""
        action_params: Dict = {}
        if self.entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = self.entity.get_action()
            action_query, action_params = format_action_filter(action, table_name="e")

        self.params = {
            **self.params,
            **math_params,
            **prop_filter_params,
            **action_params,
            "event": self.entity.id,
            "key": self.filter.breakdown,
            **date_params,
        }

        breakdown_filter_params = {
            "parsed_date_from": date_from_clause(interval_annotation, round_interval),
            "parsed_date_to": parsed_date_to,
            "actions_query": "AND {}".format(action_query) if action_query else "",
            "event_filter": "AND event = %(event)s" if not action_query else "",
            "filters": prop_filters if props_to_filter else "",
        }

        _params, _breakdown_filter_params = {}, {}

        if self.filter.breakdown_type == "cohort":
            _params, breakdown_filter, _breakdown_filter_params, breakdown_value = self._breakdown_cohort_params(
                self.team_id, self.filter, self.entity
            )
        elif self.filter.breakdown_type == "person":
            (_params, breakdown_filter, _breakdown_filter_params, breakdown_value,) = self._breakdown_person_params(
                "count(*)" if self.entity.math == "dau" else aggregate_operation,
                math_params,
                self.entity,
                self.filter,
                self.team_id,
            )
        else:
            (_params, breakdown_filter, _breakdown_filter_params, breakdown_value,) = self._breakdown_prop_params(
                "count(*)" if self.entity.math == "dau" else aggregate_operation,
                math_params,
                self.entity,
                self.filter,
                self.team_id,
            )

        if len(_params["values"]) == 0:
            # If there are no breakdown values, we are sure that there's no relevant events, so instead of adjusting
            # a "real" SELECT for this, we only include the below dummy SELECT.
            # It's a drop-in replacement for a "real" one, simply always returning 0 rows.
            # See https://github.com/PostHog/posthog/pull/5674 for context.
            return (
                "SELECT [now()] AS date, [0] AS data, '' AS breakdown_value LIMIT 0",
                {},
                lambda _: [],
            )

        self.params = {**self.params, **_params}
        breakdown_filter_params = {**breakdown_filter_params, **_breakdown_filter_params}

        if self.filter.display in TRENDS_DISPLAY_BY_VALUE:
            breakdown_filter = breakdown_filter.format(**breakdown_filter_params)
            content_sql = BREAKDOWN_AGGREGATE_QUERY_SQL.format(
                breakdown_filter=breakdown_filter,
                event_join=self._person_join_condition,
                aggregate_operation=aggregate_operation,
                breakdown_value=breakdown_value,
            )
            time_range = enumerate_time_range(self.filter, seconds_in_interval)

            return (
                content_sql,
                self.params,
                self._parse_single_aggregate_result(self.filter, self.entity, {"days": time_range}),
            )

        else:

            breakdown_filter = breakdown_filter.format(**breakdown_filter_params)

            if self.entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
                active_user_params = get_active_user_params(self.filter, self.entity, self.team_id)
                conditions = BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL.format(
                    **breakdown_filter_params, **active_user_params
                )
                inner_sql = BREAKDOWN_ACTIVE_USER_INNER_SQL.format(
                    breakdown_filter=breakdown_filter,
                    event_join=self._person_join_condition,
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
                    event_join=self._person_join_condition,
                    aggregate_operation=aggregate_operation,
                    interval_annotation=interval_annotation,
                    breakdown_value=breakdown_value,
                )

            breakdown_query = BREAKDOWN_QUERY_SQL.format(
                interval=interval_annotation, num_intervals=num_intervals, inner_sql=inner_sql,
            )
            self.params.update(
                {
                    "date_to": self.filter.date_to.strftime("%Y-%m-%d %H:%M:%S"),
                    "seconds_in_interval": seconds_in_interval,
                    "num_intervals": num_intervals,
                }
            )

            return breakdown_query, self.params, self._parse_trend_result(self.filter, self.entity)

    def _breakdown_cohort_params(self, team_id: int, filter: Filter, entity: Entity):
        cohort_queries, cohort_ids, cohort_params = format_breakdown_cohort_join_query(team_id, filter, entity=entity)
        params = {"values": cohort_ids, **cohort_params}
        breakdown_filter = BREAKDOWN_COHORT_JOIN_SQL
        breakdown_filter_params = {"cohort_queries": cohort_queries}

        return params, breakdown_filter, breakdown_filter_params, "value"

    def _breakdown_person_params(
        self, aggregate_operation: str, math_params: Dict, entity: Entity, filter: Filter, team_id: int
    ):
        values_arr = get_breakdown_person_prop_values(
            filter, entity, aggregate_operation, team_id, extra_params=math_params
        )

        # :TRICKY: We only support string breakdown for event/person properties
        assert isinstance(filter.breakdown, str)
        breakdown_value, _ = get_property_string_expr("person", filter.breakdown, "%(key)s", "person_props")

        return (
            {"values": values_arr},
            BREAKDOWN_PERSON_PROP_JOIN_SQL,
            {
                "person_query": ClickhousePersonQuery(filter, team_id).get_query(),
                "breakdown_value_expr": breakdown_value,
            },
            breakdown_value,
        )

    def _breakdown_prop_params(
        self, aggregate_operation: str, math_params: Dict, entity: Entity, filter: Filter, team_id: int
    ):
        values_arr = get_breakdown_event_prop_values(
            filter, entity, aggregate_operation, team_id, extra_params=math_params
        )

        # :TRICKY: We only support string breakdown for event/person properties
        assert isinstance(filter.breakdown, str)
        breakdown_value, _ = get_property_string_expr("events", filter.breakdown, "%(key)s", "properties")

        return (
            {"values": values_arr, "key": filter.breakdown},
            BREAKDOWN_PROP_JOIN_SQL,
            {"breakdown_value_expr": breakdown_value},
            breakdown_value,
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
        extra_label = self._determine_breakdown_label(
            breakdown_value, filter.breakdown_type, filter.breakdown, breakdown_value
        )
        label = "{} - {}".format(entity.name, extra_label)
        additional_values = {
            "label": label,
        }
        if filter.breakdown_type == "cohort":
            additional_values["breakdown_value"] = "all" if breakdown_value == ALL_USERS_COHORT_ID else breakdown_value
        else:
            additional_values["breakdown_value"] = breakdown_value

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
            return get_breakdown_cohort_name(breakdown_value)
        else:
            return str(value) or "none"

    @property
    def _should_join_person_table(self) -> bool:
        return (
            self.column_optimizer.should_query_person_properties_column
            or len(self.column_optimizer.materialized_person_columns_to_query) > 0
        )

    @property
    def _person_join_condition(self) -> str:
        if self._should_join_person_table:
            return EVENT_JOIN_PERSON_SQL
        else:
            return ""
