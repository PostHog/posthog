from typing import Any, Callable, Dict, List, Tuple

from ee.clickhouse.queries.trends.trend_event_query import TrendsEventQuery
from ee.clickhouse.queries.trends.util import enumerate_time_range, parse_response, process_math
from ee.clickhouse.queries.util import (
    format_ch_timestamp,
    get_earliest_timestamp,
    get_interval_func_ch,
    get_time_diff,
    get_trunc_func_ch,
)
from ee.clickhouse.sql.events import NULL_SQL
from ee.clickhouse.sql.trends.aggregate import AGGREGATE_SQL
from ee.clickhouse.sql.trends.volume import ACTIVE_USER_SQL, VOLUME_SQL, VOLUME_TOTAL_AGGREGATE_SQL
from posthog.constants import MONTHLY_ACTIVE, TRENDS_DISPLAY_BY_VALUE, WEEKLY_ACTIVE
from posthog.models.entity import Entity
from posthog.models.filters import Filter


class ClickhouseTrendsTotalVolume:
    def _total_volume_query(self, entity: Entity, filter: Filter, team_id: int) -> Tuple[str, Dict, Callable]:
        trunc_func = get_trunc_func_ch(filter.interval)
        interval_func = get_interval_func_ch(filter.interval)
        _, seconds_in_interval, _ = get_time_diff(filter.interval, filter.date_from, filter.date_to, team_id=team_id)
        aggregate_operation, join_condition, math_params = process_math(entity)

        trend_event_query = TrendsEventQuery(
            filter=filter,
            entity=entity,
            team_id=team_id,
            should_join_distinct_ids=True
            if join_condition != "" or entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]
            else False,
        )
        event_query, event_query_params = trend_event_query.get_query()

        content_sql_params = {
            "aggregate_operation": aggregate_operation,
            "timestamp": "e.timestamp",
            "interval": trunc_func,
        }
        params: Dict = {"team_id": team_id}
        params = {**params, **math_params, **event_query_params}

        if filter.display in TRENDS_DISPLAY_BY_VALUE:
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
                content_sql = ACTIVE_USER_SQL.format(
                    event_query=event_query,
                    **content_sql_params,
                    parsed_date_to=trend_event_query.parsed_date_to,
                    parsed_date_from=trend_event_query.parsed_date_from,
                    **trend_event_query.active_user_params
                )
            else:
                content_sql = VOLUME_SQL.format(event_query=event_query, **content_sql_params)

            null_sql = NULL_SQL.format(trunc_func=trunc_func, interval_func=interval_func)
            params["interval"] = filter.interval
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
