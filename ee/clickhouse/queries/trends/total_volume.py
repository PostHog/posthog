from datetime import timedelta
from typing import Any, Callable, Dict, List, Tuple

from django.utils import timezone

from ee.clickhouse.client import format_sql, sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.event_query import ClickhouseEventQuery
from ee.clickhouse.queries.trends.util import (
    enumerate_time_range,
    get_active_user_params,
    parse_response,
    populate_entity_params,
    process_math,
)
from ee.clickhouse.queries.util import date_from_clause, get_time_diff, get_trunc_func_ch, parse_timestamps
from ee.clickhouse.sql.events import NULL_SQL
from ee.clickhouse.sql.trends.aggregate import AGGREGATE_SQL
from ee.clickhouse.sql.trends.volume import ACTIVE_USER_SQL, VOLUME_SQL, VOLUME_TOTAL_AGGREGATE_SQL
from posthog.constants import MONTHLY_ACTIVE, TRENDS_DISPLAY_BY_VALUE, WEEKLY_ACTIVE
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filters import Filter


class ClickhouseTrendsTotalVolume:
    def _total_volume_query(self, entity: Entity, filter: Filter, team_id: int) -> Tuple[str, Dict, Callable]:

        interval_annotation = get_trunc_func_ch(filter.interval)
        num_intervals, seconds_in_interval, round_interval = get_time_diff(
            filter.interval or "day", filter.date_from, filter.date_to, team_id=team_id
        )
        _, parsed_date_to, date_params = parse_timestamps(filter=filter, team_id=team_id)

        aggregate_operation, join_condition, math_params = process_math(entity)

        content_sql_params = {
            "aggregate_operation": aggregate_operation,
            "timestamp": "e.timestamp",
            "interval": interval_annotation,
            "parsed_date_from": date_from_clause(interval_annotation, round_interval),
            "parsed_date_to": parsed_date_to,
        }
        params: Dict = {"team_id": team_id}
        params = {**params, **math_params, **date_params}

        if filter.display in TRENDS_DISPLAY_BY_VALUE:
            event_query, event_query_params = ClickhouseEventQuery(
                filter,
                entity,
                team_id,
                date_filter="{parsed_date_from} {parsed_date_to}",
                should_join_distinct_ids=True if join_condition != "" else False,
            ).get_query()
            event_query = event_query.format(**content_sql_params)
            params = {**params, **event_query_params}
            content_sql = VOLUME_TOTAL_AGGREGATE_SQL.format(event_query=event_query, **content_sql_params)
            time_range = enumerate_time_range(filter, seconds_in_interval)

            return (
                content_sql,
                params,
                lambda result: [
                    {"aggregated_value": result[0][0] if result and len(result) else 0, "days": time_range}
                ],
            )
        else:

            if entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
                event_query, event_query_params = ClickhouseEventQuery(
                    filter,
                    entity,
                    team_id,
                    date_filter="{parsed_date_from_prev_range} {parsed_date_to}",
                    should_join_distinct_ids=True,
                ).get_query()
                sql_params = get_active_user_params(filter, entity, team_id)
                params = {**params, **event_query_params}
                event_query = event_query.format(**sql_params, parsed_date_to=parsed_date_to)
                content_sql = ACTIVE_USER_SQL.format(event_query=event_query, **content_sql_params, **sql_params)
            else:
                event_query, event_query_params = ClickhouseEventQuery(
                    filter,
                    entity,
                    team_id,
                    date_filter="{parsed_date_from} {parsed_date_to}",
                    should_join_distinct_ids=True if join_condition != "" else False,
                ).get_query()
                event_query = event_query.format(**content_sql_params)
                params = {**params, **event_query_params}
                content_sql = VOLUME_SQL.format(event_query=event_query, **content_sql_params)

            null_sql = NULL_SQL.format(
                interval=interval_annotation,
                seconds_in_interval=seconds_in_interval,
                num_intervals=num_intervals,
                date_to=filter.date_to.strftime("%Y-%m-%d %H:%M:%S"),
            )
            final_query = AGGREGATE_SQL.format(null_sql=null_sql, content_sql=content_sql)
            return final_query, params, self._parse_total_volume_result(filter)

    def _parse_total_volume_result(self, filter: Filter) -> Callable:
        def _parse(result: List) -> List:
            parsed_results = []
            for _, stats in enumerate(result):
                parsed_result = parse_response(stats, filter)
                parsed_results.append(parsed_result)

            return parsed_results

        return _parse
