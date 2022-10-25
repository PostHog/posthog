import urllib.parse
from datetime import datetime
from typing import Any, Callable, Dict, List, Tuple

from posthog.constants import (
    MONTHLY_ACTIVE,
    NON_TIME_SERIES_DISPLAY_TYPES,
    TRENDS_CUMULATIVE,
    UNIQUE_USERS,
    WEEKLY_ACTIVE,
)
from posthog.models.entity import Entity
from posthog.models.event.sql import NULL_SQL
from posthog.models.filters import Filter
from posthog.models.team import Team
from posthog.queries.trends.sql import (
    ACTIVE_USERS_SQL,
    AGGREGATE_SQL,
    CUMULATIVE_SQL,
    SESSION_DURATION_AGGREGATE_SQL,
    SESSION_DURATION_SQL,
    VOLUME_AGGREGATE_SQL,
    VOLUME_PER_ACTOR_AGGREGATE_SQL,
    VOLUME_PER_ACTOR_SQL,
    VOLUME_SQL,
)
from posthog.queries.trends.trends_event_query import TrendsEventQuery
from posthog.queries.trends.util import (
    COUNT_PER_ACTOR_MATH_FUNCTIONS,
    PROPERTY_MATH_FUNCTIONS,
    enumerate_time_range,
    parse_response,
    process_math,
)
from posthog.queries.util import TIME_IN_SECONDS, get_interval_func_ch, get_trunc_func_ch, start_of_week_fix
from posthog.utils import encode_get_request_params


class TrendsTotalVolume:
    def _total_volume_query(self, entity: Entity, filter: Filter, team: Team) -> Tuple[str, Dict, Callable]:

        trunc_func = get_trunc_func_ch(filter.interval)
        interval_func = get_interval_func_ch(filter.interval)
        aggregate_operation, join_condition, math_params = process_math(entity, team, person_id_alias="person_id")

        trend_event_query = TrendsEventQuery(
            filter=filter,
            entity=entity,
            team=team,
            should_join_distinct_ids=True
            if join_condition != ""
            or (entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE] and not team.aggregate_users_by_distinct_id)
            else False,
            using_person_on_events=team.actor_on_events_querying_enabled,
        )
        event_query, event_query_params = trend_event_query.get_query()

        content_sql_params = {
            "aggregate_operation": aggregate_operation,
            "timestamp": "e.timestamp",
            "interval": trunc_func,
            "interval_func": interval_func,
        }
        params: Dict = {"team_id": team.id, "timezone": team.timezone}
        params = {**params, **math_params, **event_query_params}

        if filter.display in NON_TIME_SERIES_DISPLAY_TYPES:
            if entity.math in PROPERTY_MATH_FUNCTIONS and entity.math_property == "$session_duration":
                # TODO: When we add more person/group properties to math_property,
                # generalise this query to work for everything, not just sessions.
                content_sql = SESSION_DURATION_AGGREGATE_SQL.format(event_query=event_query, **content_sql_params)
            elif entity.math in COUNT_PER_ACTOR_MATH_FUNCTIONS:
                content_sql = VOLUME_PER_ACTOR_AGGREGATE_SQL.format(
                    event_query=event_query,
                    **content_sql_params,
                    aggregator="distinct_id" if team.aggregate_users_by_distinct_id else "person_id",
                )
            else:
                content_sql = VOLUME_AGGREGATE_SQL.format(event_query=event_query, **content_sql_params)

            return (content_sql, params, self._parse_aggregate_volume_result(filter, entity, team.id))
        else:

            if entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
                content_sql = ACTIVE_USERS_SQL.format(
                    event_query=event_query,
                    **content_sql_params,
                    parsed_date_to=trend_event_query.parsed_date_to,
                    parsed_date_from=trend_event_query.parsed_date_from,
                    aggregator="distinct_id" if team.aggregate_users_by_distinct_id else "person_id",
                    start_of_week_fix=start_of_week_fix(filter.interval),
                    **trend_event_query.active_user_params,
                )
            elif filter.display == TRENDS_CUMULATIVE and entity.math == UNIQUE_USERS:
                # TODO: for groups aggregation as well
                cumulative_sql = CUMULATIVE_SQL.format(event_query=event_query)
                content_sql = VOLUME_SQL.format(
                    event_query=cumulative_sql,
                    start_of_week_fix=start_of_week_fix(filter.interval),
                    **content_sql_params,
                )
            elif entity.math in COUNT_PER_ACTOR_MATH_FUNCTIONS:
                # Calculate average number of events per actor
                # (only including actors with at least one matching event in a period)
                content_sql = VOLUME_PER_ACTOR_SQL.format(
                    event_query=event_query,
                    start_of_week_fix=start_of_week_fix(filter.interval),
                    **content_sql_params,
                    aggregator="distinct_id" if team.aggregate_users_by_distinct_id else "person_id",
                )
            elif entity.math_property == "$session_duration":
                # TODO: When we add more person/group properties to math_property,
                # generalise this query to work for everything, not just sessions.
                content_sql = SESSION_DURATION_SQL.format(
                    event_query=event_query, start_of_week_fix=start_of_week_fix(filter.interval), **content_sql_params
                )
            else:
                content_sql = VOLUME_SQL.format(
                    event_query=event_query, start_of_week_fix=start_of_week_fix(filter.interval), **content_sql_params
                )

            null_sql = NULL_SQL.format(
                trunc_func=trunc_func,
                interval_func=interval_func,
                start_of_week_fix=start_of_week_fix(filter.interval),
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

            final_query = AGGREGATE_SQL.format(
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
                    parsed_result = parse_response(stats, filter)
                    parsed_result.update({"persons_urls": self._get_persons_url(filter, entity, team.pk, stats[0])})
                    parsed_results.append(parsed_result)
                    parsed_result.update({"filter": filter.to_dict()})
            return parsed_results

        return _parse

    def _parse_aggregate_volume_result(self, filter: Filter, entity: Entity, team_id: int) -> Callable:
        def _parse(result: List) -> List:
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
                    "aggregated_value": result[0][0] if result and len(result) else 0,
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
        self, filter: Filter, entity: Entity, team_id: int, dates: List[datetime]
    ) -> List[Dict[str, Any]]:
        persons_url = []
        for date in dates:
            filter_params = filter.to_params()
            extra_params = {
                "entity_id": entity.id,
                "entity_type": entity.type,
                "entity_math": entity.math,
                "date_from": filter.date_from if filter.display == TRENDS_CUMULATIVE else date,
                "date_to": date,
                "entity_order": entity.order,
            }

            parsed_params: Dict[str, str] = encode_get_request_params({**filter_params, **extra_params})
            persons_url.append(
                {
                    "filter": extra_params,
                    "url": f"api/projects/{team_id}/persons/trends/?{urllib.parse.urlencode(parsed_params)}",
                }
            )
        return persons_url
