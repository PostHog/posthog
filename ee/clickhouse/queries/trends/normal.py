from typing import Any, Dict, List

from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.trends.util import parse_response, process_math
from ee.clickhouse.queries.util import get_interval_annotation_ch, get_time_diff, parse_timestamps
from ee.clickhouse.sql.events import NULL_SQL
from ee.clickhouse.sql.trends.aggregate import AGGREGATE_SQL
from ee.clickhouse.sql.trends.volume import VOLUME_ACTIONS_SQL, VOLUME_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filters import Filter


class ClickhouseTrendsNormal:
    def _format_normal_query(self, entity: Entity, filter: Filter, team_id: int) -> List[Dict[str, Any]]:

        interval_annotation = get_interval_annotation_ch(filter.interval)
        num_intervals, seconds_in_interval = get_time_diff(filter.interval or "day", filter.date_from, filter.date_to)
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)

        props_to_filter = [*filter.properties, *entity.properties]
        prop_filters, prop_filter_params = parse_prop_clauses(props_to_filter, team_id)

        aggregate_operation, join_condition, math_params = process_math(entity)

        params: Dict = {"team_id": team_id}
        params = {**params, **prop_filter_params, **math_params}
        content_sql_params = {
            "interval": interval_annotation,
            "timestamp": "timestamp",
            "team_id": team_id,
            "parsed_date_from": parsed_date_from,
            "parsed_date_to": parsed_date_to,
            "filters": prop_filters,
            "event_join": join_condition,
            "aggregate_operation": aggregate_operation,
        }

        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            try:
                action = Action.objects.get(pk=entity.id)
                action_query, action_params = format_action_filter(action)
                params = {**params, **action_params}
                content_sql = VOLUME_ACTIONS_SQL
                content_sql_params = {**content_sql_params, "actions_query": action_query}
            except:
                return []
        else:
            content_sql = VOLUME_SQL
            params = {**params, "event": entity.id}
        null_sql = NULL_SQL.format(
            interval=interval_annotation,
            seconds_in_interval=seconds_in_interval,
            num_intervals=num_intervals,
            date_to=filter.date_to.strftime("%Y-%m-%d %H:%M:%S"),
        )
        content_sql = content_sql.format(**content_sql_params)
        final_query = AGGREGATE_SQL.format(null_sql=null_sql, content_sql=content_sql)

        try:
            result = sync_execute(final_query, params)

        except:
            result = []

        parsed_results = []
        for _, stats in enumerate(result):
            parsed_result = parse_response(stats, filter)
            parsed_results.append(parsed_result)

        return parsed_results
