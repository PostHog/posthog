from typing import Any, Callable, Dict, List, Tuple

from django.utils import timezone

from ee.clickhouse.client import format_sql, sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.trends.util import parse_response, process_math
from ee.clickhouse.queries.util import (
    date_from_clause,
    format_ch_timestamp,
    get_earliest_timestamp,
    get_time_diff,
    get_trunc_func_ch,
    parse_timestamps,
)
from ee.clickhouse.sql.events import NULL_SQL
from ee.clickhouse.sql.trends.aggregate import AGGREGATE_SQL
from ee.clickhouse.sql.trends.volume import (
    ACTIVE_USER_SQL,
    VOLUME__TOTAL_AGGREGATE_ACTIONS_SQL,
    VOLUME_ACTIONS_SQL,
    VOLUME_SQL,
    VOLUME_TOTAL_AGGREGATE_SQL,
)
from posthog.constants import MONTHLY_ACTIVE, TREND_FILTER_TYPE_ACTIONS, TRENDS_DISPLAY_BY_VALUE, WEEKLY_ACTIVE
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filters import Filter


class ClickhouseTrendsNormal:
    def _normal_query(self, entity: Entity, filter: Filter, team_id: int) -> Tuple[str, Dict, Callable]:

        interval_annotation = get_trunc_func_ch(filter.interval)
        num_intervals, seconds_in_interval, round_interval = get_time_diff(
            filter.interval or "day", filter.date_from, filter.date_to, team_id=team_id
        )
        _, parsed_date_to, date_params = parse_timestamps(filter=filter, team_id=team_id)

        props_to_filter = [*filter.properties, *entity.properties]
        prop_filters, prop_filter_params = parse_prop_clauses(
            props_to_filter, team_id, filter_test_accounts=filter.filter_test_accounts
        )

        aggregate_operation, join_condition, math_params = process_math(entity)

        params: Dict = {"team_id": team_id}
        params = {**params, **prop_filter_params, **math_params, **date_params}
        content_sql_params = {
            "interval": interval_annotation,
            "parsed_date_from": date_from_clause(interval_annotation, round_interval),
            "parsed_date_to": parsed_date_to,
            "timestamp": "timestamp",
            "filters": prop_filters,
            "event_join": join_condition,
            "aggregate_operation": aggregate_operation,
            "entity_query": "AND {actions_query}"
            if entity.type == TREND_FILTER_TYPE_ACTIONS
            else "AND event = %(event)s",
        }

        entity_params, entity_format_params = self._populate_entity_params(entity)
        params = {**params, **entity_params}
        content_sql_params = {**content_sql_params, **entity_format_params}

        if filter.display in TRENDS_DISPLAY_BY_VALUE:
            content_sql = VOLUME_TOTAL_AGGREGATE_SQL.format(**content_sql_params)

            return (
                content_sql,
                params,
                lambda result: [{"aggregated_value": result[0][0] if result and len(result) else 0}],
            )
        elif entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
            sql_params = self.get_active_user_params(filter, entity, team_id)
            final_query = ACTIVE_USER_SQL.format(**content_sql_params, **sql_params)
            return final_query, params, self._parse_normal_result(filter)
        else:
            content_sql = VOLUME_SQL.format(**content_sql_params)

            null_sql = NULL_SQL.format(
                interval=interval_annotation,
                seconds_in_interval=seconds_in_interval,
                num_intervals=num_intervals,
                date_to=filter.date_to.strftime("%Y-%m-%d %H:%M:%S"),
            )
            final_query = AGGREGATE_SQL.format(null_sql=null_sql, content_sql=content_sql)

            return final_query, params, self._parse_normal_result(filter)

    def _parse_normal_result(self, filter: Filter) -> Callable:
        def _parse(result: List) -> List:
            parsed_results = []
            for _, stats in enumerate(result):
                parsed_result = parse_response(stats, filter)
                parsed_results.append(parsed_result)

            return parsed_results

        return _parse

    def _populate_entity_params(self, entity: Entity) -> Tuple[Dict, Dict]:
        params, content_sql_params = {}, {}
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            try:
                action = Action.objects.get(pk=entity.id)
                action_query, action_params = format_action_filter(action)
                params = {**action_params}
                content_sql_params = {"actions_query": action_query}
            except:
                raise ValueError("Action does not exist")
        else:
            params = {"event": entity.id}

        return params, content_sql_params

    def get_active_user_params(self, filter: Filter, entity: Entity, team_id: int) -> Dict[str, Any]:
        params = {}
        params.update({"interval": "7 DAY" if entity.math == WEEKLY_ACTIVE else "30 day"})

        if filter.date_from:
            params.update({"parsed_date_from_prev_range": format_ch_timestamp(filter.date_from, filter)})
        else:
            try:
                earliest_date = get_earliest_timestamp(team_id)
            except IndexError:
                raise ValueError("Active User queries require a lower date bound")
            else:
                params.update({"parsed_date_from_prev_range": format_ch_timestamp(earliest_date, filter)})

        return params
