import urllib.parse
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, Union

from posthog.schema import PersonsOnEventsMode

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
from posthog.queries.event_query import EventQuery
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
from posthog.queries.trends.trends_event_query import TrendsEventQuery
from posthog.queries.trends.util import (
    COUNT_PER_ACTOR_MATH_FUNCTIONS,
    PROPERTY_MATH_FUNCTIONS,
    determine_aggregator,
    enumerate_time_range,
    offset_time_series_date_by_interval,
    parse_response,
    process_math,
)
from posthog.queries.util import TIME_IN_SECONDS, get_interval_func_ch, get_start_of_interval_sql
from posthog.utils import encode_get_request_params, generate_short_id


class TrendsTotalVolume:
    DISTINCT_ID_TABLE_ALIAS = EventQuery.DISTINCT_ID_TABLE_ALIAS
    EVENT_TABLE_ALIAS = EventQuery.EVENT_TABLE_ALIAS
    PERSON_ID_OVERRIDES_TABLE_ALIAS = EventQuery.PERSON_ID_OVERRIDES_TABLE_ALIAS

    def _total_volume_query(self, entity: Entity, filter: Filter, team: Team) -> tuple[str, dict, Callable]:
        interval_func = get_interval_func_ch(filter.interval)

        person_id_alias = f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id"
        if team.person_on_events_mode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS:
            person_id_alias = f"if(notEmpty({self.PERSON_ID_OVERRIDES_TABLE_ALIAS}.person_id), {self.PERSON_ID_OVERRIDES_TABLE_ALIAS}.person_id, {self.EVENT_TABLE_ALIAS}.person_id)"
        elif team.person_on_events_mode == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS:
            person_id_alias = f"{self.EVENT_TABLE_ALIAS}.person_id"

        aggregate_operation, join_condition, math_params = process_math(
            entity,
            team,
            filter=filter,
            event_table_alias=TrendsEventQuery.EVENT_TABLE_ALIAS,
            person_id_alias=person_id_alias,
        )

        trend_event_query = TrendsEventQuery(
            filter=filter,
            entity=entity,
            team=team,
            should_join_distinct_ids=(
                True
                if join_condition != ""
                or (entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE] and not team.aggregate_users_by_distinct_id)
                else False
            ),
            person_on_events_mode=team.person_on_events_mode,
        )
        event_query_base, event_query_params = trend_event_query.get_query_base()

        content_sql_params = {
            "aggregate_operation": aggregate_operation,
            "timestamp": "e.timestamp",
            "interval_func": interval_func,
        }
        params: dict = {"team_id": team.id, "timezone": team.timezone}
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
                if entity.math == "hogql":
                    tag_queries(trend_volume_type="hogql")
                else:
                    tag_queries(trend_volume_type="volume_aggregate")
                content_sql = VOLUME_AGGREGATE_SQL.format(event_query_base=event_query_base, **content_sql_params)

            return (
                content_sql,
                params,
                self._parse_aggregate_volume_result(filter, entity, team.id),
            )
        else:
            tag_queries(trend_volume_display="time_series")
            null_sql = NULL_SQL.format(
                date_to_truncated=get_start_of_interval_sql(filter.interval, team=team, source="%(date_to)s"),
                date_from_truncated=get_start_of_interval_sql(filter.interval, team=team, source="%(date_from)s"),
                interval_func=interval_func,
            )

            if entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
                tag_queries(trend_volume_type="active_users")
                content_sql = ACTIVE_USERS_SQL.format(
                    event_query_base=event_query_base,
                    parsed_date_to=trend_event_query.parsed_date_to,
                    parsed_date_from=trend_event_query.parsed_date_from,
                    aggregator=determine_aggregator(entity, team),  # TODO: Support groups officialy and with tests
                    date_to_truncated=get_start_of_interval_sql(filter.interval, team=team, source="%(date_to)s"),
                    date_from_active_users_adjusted_truncated=get_start_of_interval_sql(
                        filter.interval,
                        team=team,
                        source="%(date_from_active_users_adjusted)s",
                    ),
                    **content_sql_params,
                    **trend_event_query.active_user_params,
                )
            elif filter.display == TRENDS_CUMULATIVE and entity.math in (
                UNIQUE_USERS,
                UNIQUE_GROUPS,
            ):
                # :TODO: Consider using bitmap-per-date to speed this up
                tag_queries(trend_volume_type="cumulative_actors")
                cumulative_sql = CUMULATIVE_SQL.format(
                    actor_expression=determine_aggregator(entity, team),
                    event_query_base=event_query_base,
                )
                content_sql_params["aggregate_operation"] = "COUNT(DISTINCT actor_id)"
                content_sql = VOLUME_SQL.format(
                    timestamp_truncated=get_start_of_interval_sql(
                        filter.interval, team=team, source="first_seen_timestamp"
                    ),
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
                    timestamp_truncated=get_start_of_interval_sql(filter.interval, team=team),
                    **content_sql_params,
                )
            elif entity.math_property == "$session_duration":
                tag_queries(trend_volume_type="session_duration_math")
                # TODO: When we add more person/group properties to math_property,
                # generalise this query to work for everything, not just sessions.
                content_sql = SESSION_DURATION_SQL.format(
                    event_query_base=event_query_base,
                    timestamp_truncated=get_start_of_interval_sql(filter.interval, team=team),
                    **content_sql_params,
                )
            else:
                if entity.math == "hogql":
                    tag_queries(trend_volume_type="hogql")
                else:
                    tag_queries(trend_volume_type="volume")
                content_sql = VOLUME_SQL.format(
                    event_query_base=event_query_base,
                    timestamp_truncated=get_start_of_interval_sql(filter.interval, team=team),
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
        def _parse(result: list) -> list:
            parsed_results = []
            if result is not None:
                for stats in result:
                    parsed_result = parse_response(stats, filter, entity=entity)
                    point_dates: list[Union[datetime, date]] = stats[0]
                    # Ensure we have datetimes for all points
                    point_datetimes: list[datetime] = [
                        datetime.combine(d, datetime.min.time()) if not isinstance(d, datetime) else d
                        for d in point_dates
                    ]
                    parsed_result.update({"persons_urls": self._get_persons_url(filter, entity, team, point_datetimes)})
                    parsed_results.append(parsed_result)
                    parsed_result.update({"filter": filter.to_dict()})
            return parsed_results

        return _parse

    def _parse_aggregate_volume_result(self, filter: Filter, entity: Entity, team_id: int) -> Callable:
        def _parse(result: list) -> list:
            aggregated_value = result[0][0] if result else 0
            seconds_in_interval = TIME_IN_SECONDS[filter.interval]
            time_range = enumerate_time_range(filter, seconds_in_interval)
            filter_params = filter.to_params()
            extra_params = {
                "entity_id": entity.id,
                "entity_type": entity.type,
                "entity_math": entity.math,
                "entity_order": entity.order,
            }
            parsed_params: dict[str, str] = encode_get_request_params({**filter_params, **extra_params})
            cache_invalidation_key = generate_short_id()

            return [
                {
                    "aggregated_value": aggregated_value,
                    "days": time_range,
                    "filter": filter_params,
                    "persons": {
                        "filter": extra_params,
                        "url": f"api/projects/{team_id}/persons/trends/?{urllib.parse.urlencode(parsed_params)}&cache_invalidation_key={cache_invalidation_key}",
                    },
                }
            ]

        return _parse

    def _offset_date_from(self, point_datetime: datetime, filter: Filter, entity: Entity) -> datetime | None:
        if filter.display == TRENDS_CUMULATIVE:
            return filter.date_from
        elif entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
            # :TRICKY: We have to offset the date by one, as the final query already subtracts 7 days
            return point_datetime + timedelta(days=1)
        else:
            return point_datetime

    def _offset_date_to(self, point_datetime: datetime, filter: Filter, entity: Entity, team: Team) -> datetime:
        if entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
            return point_datetime
        else:
            return offset_time_series_date_by_interval(point_datetime, filter=filter, team=team)

    def _get_persons_url(
        self,
        filter: Filter,
        entity: Entity,
        team: Team,
        point_datetimes: list[datetime],
    ) -> list[dict[str, Any]]:
        persons_url = []
        cache_invalidation_key = generate_short_id()
        for point_datetime in point_datetimes:
            filter_params = filter.to_params()
            extra_params = {
                "entity_id": entity.id,
                "entity_type": entity.type,
                "entity_math": entity.math,
                "date_from": self._offset_date_from(point_datetime, filter=filter, entity=entity),
                "date_to": self._offset_date_to(point_datetime, filter=filter, entity=entity, team=team),
                "entity_order": entity.order,
            }

            parsed_params: dict[str, str] = encode_get_request_params({**filter_params, **extra_params})
            persons_url.append(
                {
                    "filter": extra_params,
                    "url": f"api/projects/{team.pk}/persons/trends/?{urllib.parse.urlencode(parsed_params)}&cache_invalidation_key={cache_invalidation_key}",
                }
            )
        return persons_url
