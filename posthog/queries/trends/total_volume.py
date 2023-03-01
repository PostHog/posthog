import urllib.parse
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Tuple, Union

from posthog.clickhouse.query_tagging import tag_queries
from posthog.constants import (
    MONTHLY_ACTIVE,
    NON_TIME_SERIES_DISPLAY_TYPES,
    TRENDS_CUMULATIVE,
    UNIQUE_GROUPS,
    UNIQUE_USERS,
    WEEKLY_ACTIVE,
)
from posthog.models.entity import Entity
from posthog.models.event.sql import NULL_SQL
from posthog.models.filters import Filter
from posthog.models.team import Team
from posthog.queries.trends.sql import (
    ACTIVE_USERS_AGGREGATE_SQL,
    ACTIVE_USERS_SQL,
    CUMULATIVE_SQL,
    FINAL_TIME_SERIES_SQL,
    SESSION_DURATION_AGGREGATE_SQL,
    SESSION_DURATION_SQL,
    VOLUME_AGGREGATE_SQL,
    VOLUME_PER_ACTOR_AGGREGATE_SQL,
    VOLUME_PER_ACTOR_SQL,
    VOLUME_SQL,
)
from posthog.queries.trends.trends_actors import offset_time_series_date_by_interval
from posthog.queries.trends.trends_event_query import TrendsEventQuery
from posthog.queries.trends.util import (
    COUNT_PER_ACTOR_MATH_FUNCTIONS,
    PROPERTY_MATH_FUNCTIONS,
    determine_aggregator,
    ensure_value_is_json_serializable,
    enumerate_time_range,
    parse_response,
    process_math,
)
from posthog.queries.util import TIME_IN_SECONDS, get_interval_func_ch, get_trunc_func_ch
from posthog.utils import encode_get_request_params


class TrendsTotalVolume:
    def _total_volume_query(self, entity: Entity, filter: Filter, team: Team) -> Tuple[str, Dict, Callable]:

        trunc_func = get_trunc_func_ch(filter.interval)
        interval_func = get_interval_func_ch(filter.interval)
        aggregate_operation, join_condition, math_params = process_math(
            entity,
            team,
            event_table_alias=TrendsEventQuery.EVENT_TABLE_ALIAS,
            person_id_alias=f"person_id" if team.person_on_events_querying_enabled else "pdi.person_id",
        )

        trend_event_query = TrendsEventQuery(
            filter=filter,
            entity=entity,
            team=team,
            should_join_distinct_ids=True
            if join_condition != ""
            or (entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE] and not team.aggregate_users_by_distinct_id)
            else False,
            using_person_on_events=team.person_on_events_querying_enabled,
        )
        event_query_base, event_query_params = trend_event_query.get_query_base()

        content_sql_params = {
            "aggregate_operation": aggregate_operation,
            "timestamp": "e.timestamp",
            "interval": trunc_func,
            "interval_func": interval_func,
        }
        params: Dict = {"team_id": team.id, "timezone": team.timezone}
        params = {**params, **math_params, **event_query_params}

        if filter.display in NON_TIME_SERIES_DISPLAY_TYPES:
            tag_queries(trend_volume_display="non_time_series")
            if entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
                tag_queries(trend_volume_type="active_users")
                content_sql = ACTIVE_USERS_AGGREGATE_SQL.format(
                    event_query_base=event_query_base,
                    aggregator="distinct_id" if team.aggregate_users_by_distinct_id else "person_id",
                    **content_sql_params,
                    **trend_event_query.active_user_params,
                )
            elif entity.math in PROPERTY_MATH_FUNCTIONS and entity.math_property == "$session_duration":
                # TODO: When we add more person/group properties to math_property,
                # generalise this query to work for everything, not just sessions.
                tag_queries(trend_volume_type="session_duration_math")
                content_sql = SESSION_DURATION_AGGREGATE_SQL.format(
                    event_query_base=event_query_base, **content_sql_params
                )
            elif entity.math in COUNT_PER_ACTOR_MATH_FUNCTIONS:
                tag_queries(trend_volume_type="count_per_actor")
                content_sql = VOLUME_PER_ACTOR_AGGREGATE_SQL.format(
                    event_query_base=event_query_base,
                    **content_sql_params,
                    aggregator=determine_aggregator(entity, team),
                )
            else:
                tag_queries(trend_volume_type="volume_aggregate")
                content_sql = VOLUME_AGGREGATE_SQL.format(event_query_base=event_query_base, **content_sql_params)

            return (content_sql, params, self._parse_aggregate_volume_result(filter, entity, team.id))
        else:
            tag_queries(trend_volume_display="time_series")
            null_sql = NULL_SQL.format(trunc_func=trunc_func, interval_func=interval_func)

            if entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
                tag_queries(trend_volume_type="active_users")
                content_sql = ACTIVE_USERS_SQL.format(
                    event_query_base=event_query_base,
                    parsed_date_to=trend_event_query.parsed_date_to,
                    parsed_date_from=trend_event_query.parsed_date_from,
                    aggregator=determine_aggregator(entity, team),  # TODO: Support groups officialy and with tests
                    **content_sql_params,
                    **trend_event_query.active_user_params,
                )
            elif filter.display == TRENDS_CUMULATIVE and entity.math in (UNIQUE_USERS, UNIQUE_GROUPS):
                # :TODO: Consider using bitmap-per-date to speed this up
                tag_queries(trend_volume_type="cumulative_actors")
                cumulative_sql = CUMULATIVE_SQL.format(
                    actor_expression=determine_aggregator(entity, team),
                    event_query_base=event_query_base,
                )
                content_sql_params["aggregate_operation"] = "COUNT(DISTINCT actor_id)"
                content_sql = VOLUME_SQL.format(
                    timestamp_column="first_seen_timestamp",
                    event_query_base=f"FROM ({cumulative_sql})",
                    **content_sql_params,
                )
            elif entity.math in COUNT_PER_ACTOR_MATH_FUNCTIONS:
                tag_queries(trend_volume_type="count_per_actor")
                # Calculate average number of events per actor
                # (only including actors with at least one matching event in a period)
                content_sql = VOLUME_PER_ACTOR_SQL.format(
                    event_query_base=event_query_base,
                    aggregator=determine_aggregator(entity, team),
                    **content_sql_params,
                )
            elif entity.math_property == "$session_duration":
                tag_queries(trend_volume_type="session_duration_math")
                # TODO: When we add more person/group properties to math_property,
                # generalise this query to work for everything, not just sessions.
                content_sql = SESSION_DURATION_SQL.format(
                    event_query_base=event_query_base,
                    **content_sql_params,
                )
            else:
                tag_queries(trend_volume_type="volume")
                content_sql = VOLUME_SQL.format(
                    timestamp_column="timestamp",
                    event_query_base=event_query_base,
                    **content_sql_params,
                )

            params["interval"] = filter.interval

            # If we have a smoothing interval > 1 then add in the sql to
            # handling rolling average. Else just do a sum. This is possibly an
            # nessacary optimization.
            if filter.smoothing_intervals > 1:
                smoothing_operation = f"""
                    AVG(SUM(total))
                    OVER (
                        ORDER BY day_start
                        ROWS BETWEEN {filter.smoothing_intervals - 1} PRECEDING
                        AND CURRENT ROW
                    )"""
            else:
                smoothing_operation = "SUM(total)"

            final_query = FINAL_TIME_SERIES_SQL.format(
                null_sql=null_sql,
                content_sql=content_sql,
                smoothing_operation=smoothing_operation,
                aggregate="count" if filter.smoothing_intervals < 2 else "floor(count)",
            )

            return final_query, params, self._parse_total_volume_result(filter, entity, team)

    def _parse_total_volume_result(self, filter: Filter, entity: Entity, team: Team) -> Callable:
        def _parse(result: List) -> List:
            parsed_results = []
            if result is not None:
                for stats in result:
                    parsed_result = parse_response(stats, filter, entity=entity)
                    point_dates: List[Union[datetime, date]] = stats[0]
                    # Ensure we have datetimes for all points
                    point_datetimes: List[datetime] = [
                        datetime.combine(d, datetime.min.time()) if not isinstance(d, datetime) else d
                        for d in point_dates
                    ]
                    parsed_result.update({"persons_urls": self._get_persons_url(filter, entity, team, point_datetimes)})
                    parsed_results.append(parsed_result)
                    parsed_result.update({"filter": filter.to_dict()})
            return parsed_results

        return _parse

    def _parse_aggregate_volume_result(self, filter: Filter, entity: Entity, team_id: int) -> Callable:
        def _parse(result: List) -> List:
            aggregated_value = ensure_value_is_json_serializable(result[0][0]) if result and len(result) else 0
            seconds_in_interval = TIME_IN_SECONDS[filter.interval]
            time_range = enumerate_time_range(filter, seconds_in_interval)
            filter_params = filter.to_params()
            extra_params = {
                "entity_id": entity.id,
                "entity_type": entity.type,
                "entity_math": entity.math,
                "entity_order": entity.order,
            }
            parsed_params: Dict[str, str] = encode_get_request_params({**filter_params, **extra_params})

            return [
                {
                    "aggregated_value": aggregated_value,
                    "days": time_range,
                    "filter": filter_params,
                    "persons": {
                        "filter": extra_params,
                        "url": f"api/projects/{team_id}/persons/trends/?{urllib.parse.urlencode(parsed_params)}",
                    },
                }
            ]

        return _parse

    def _get_persons_url(
        self, filter: Filter, entity: Entity, team: Team, point_datetimes: List[datetime]
    ) -> List[Dict[str, Any]]:
        persons_url = []
        for point_datetime in point_datetimes:
            filter_params = filter.to_params()
            extra_params = {
                "entity_id": entity.id,
                "entity_type": entity.type,
                "entity_math": entity.math,
                "date_from": filter.date_from if filter.display == TRENDS_CUMULATIVE else point_datetime,
                "date_to": offset_time_series_date_by_interval(point_datetime, filter=filter, team=team),
                "entity_order": entity.order,
            }

            parsed_params: Dict[str, str] = encode_get_request_params({**filter_params, **extra_params})
            persons_url.append(
                {
                    "filter": extra_params,
                    "url": f"api/projects/{team.pk}/persons/trends/?{urllib.parse.urlencode(parsed_params)}",
                }
            )
        return persons_url
