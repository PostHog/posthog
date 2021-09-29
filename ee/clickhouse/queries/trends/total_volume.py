from typing import Any, Callable, Dict, List, Tuple

from ee.clickhouse.queries.trends.trend_event_query import TrendsEventQuery
from ee.clickhouse.queries.trends.util import parse_response, process_math
from ee.clickhouse.queries.util import (
    format_ch_timestamp,
    get_earliest_timestamp,
    get_interval_func_ch,
    get_trunc_func_ch,
)
from ee.clickhouse.sql.trends.volume import ACTIVE_USER_SQL, VOLUME_SQL
from posthog.constants import MONTHLY_ACTIVE, TRENDS_DISPLAY_BY_VALUE, WEEKLY_ACTIVE
from posthog.models.entity import Entity
from posthog.models.filters import Filter


class ClickhouseTrendsTotalVolume:
    def _total_volume_query(self, entity: Entity, filter: Filter, team_id: int) -> Tuple[str, Dict, Callable]:
        trunc_func = get_trunc_func_ch(filter.interval)
        interval_func = get_interval_func_ch(filter.interval)
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
            "interval_func": interval_func,
        }
        params: Dict = {"team_id": team_id}
        params = {**params, **math_params, **event_query_params}

        if entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
            final_query = ACTIVE_USER_SQL.format(
                event_query=event_query,
                **content_sql_params,
                parsed_date_to=trend_event_query.parsed_date_to,
                parsed_date_from=trend_event_query.parsed_date_from,
                **trend_event_query.active_user_params
            )
        else:
            final_query = VOLUME_SQL.format(event_query=event_query, **content_sql_params)

        params["date_from"] = format_ch_timestamp(filter.date_from or get_earliest_timestamp(team_id), filter)
        params["date_to"] = format_ch_timestamp(filter.date_to, filter)
        params["interval"] = filter.interval
        return final_query, params, self._parse_total_volume_result(filter)

    def _parse_total_volume_result(self, filter: Filter) -> Callable:
        def _parse(result: List) -> List:
            # NOTE: there's some implicit coupling here:
            #
            #        1. the ordering of the fields we get back, (date, value)
            #        2. that the last row is always the `WITH TOTALS` result
            #
            #  The last row relates to the `WITH TOTALS` from the clickhouse query
            values_without_totals, (_, aggregated_value) = result[:-1], result[-1]

            # Separate dates and values, as desired for the REST API response
            dates, values = zip(*sorted(values_without_totals))

            parsed_result = parse_response([dates, values], filter)

            # NOTE: to maintain backwards compatability here from previous behaviour, we exclude the
            #        `aggregated_value` for some filter.display.
            # TODO: verify if updating to always including `aggregated_value` would break anything. It
            #       would be simpler to not have to have this special casing in here.
            if filter.display in TRENDS_DISPLAY_BY_VALUE:
                parsed_result["aggregated_value"] = aggregated_value

            return [parsed_result]

        return _parse
