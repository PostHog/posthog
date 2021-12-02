from typing import Dict, Tuple

from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from ee.clickhouse.queries.util import get_trunc_func_ch
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS
from ee.clickhouse.sql.retention.people_in_period import (
    DEFAULT_REFERENCE_EVENT_PEOPLE_PER_PERIOD_SQL,
    DEFAULT_REFERENCE_EVENT_UNIQUE_PEOPLE_PER_PERIOD_SQL,
    REFERENCE_EVENT_PEOPLE_PER_PERIOD_SQL,
    REFERENCE_EVENT_UNIQUE_PEOPLE_PER_PERIOD_SQL,
    RETENTION_PEOPLE_PER_PERIOD_SQL,
)
from ee.clickhouse.sql.retention.retention import REFERENCE_EVENT_SQL, REFERENCE_EVENT_UNIQUE_SQL, RETENTION_PEOPLE_SQL
from posthog.constants import RETENTION_FIRST_TIME, TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filters import RetentionFilter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.team import Team


def _get_condition(target_entity: Entity, table: str, prepend: str = "") -> Tuple[str, Dict]:
    if target_entity.type == TREND_FILTER_TYPE_ACTIONS:
        action = Action.objects.get(pk=target_entity.id)
        action_query, params = format_action_filter(action, prepend=prepend, use_loop=False)
        condition = action_query
    elif target_entity.type == TREND_FILTER_TYPE_EVENTS:
        condition = "{}.event = %({}_event)s".format(table, prepend)
        params = {"{}_event".format(prepend): target_entity.id}
    else:
        condition = "{}.event = %({}_event)s".format(table, prepend)
        params = {"{}_event".format(prepend): "$pageview"}
    return condition, params


class ClickhouseRetentionActors(ActorBaseQuery):
    _filter: RetentionFilter

    def __init__(self, team: Team, filter: RetentionFilter):
        super().__init__(team, filter)

    @cached_property
    def is_aggregating_by_groups(self) -> bool:
        return self._filter.aggregation_group_type_index is not None

    def actor_query(self) -> Tuple[str, Dict]:
        period = self._filter.period
        is_first_time_retention = self._filter.retention_type == RETENTION_FIRST_TIME
        trunc_func = get_trunc_func_ch(period)
        prop_filters, prop_filter_params = parse_prop_clauses(self._filter.properties)

        returning_entity = (
            self._filter.returning_entity if self._filter.selected_interval > 0 else self._filter.target_entity
        )
        target_query, target_params = _get_condition(self._filter.target_entity, table="e")
        target_query_formatted = "AND {target_query}".format(target_query=target_query)
        return_query, return_params = _get_condition(returning_entity, table="e", prepend="returning")
        return_query_formatted = "AND {return_query}".format(return_query=return_query)

        reference_event_query = (REFERENCE_EVENT_UNIQUE_SQL if is_first_time_retention else REFERENCE_EVENT_SQL).format(
            target_query=target_query_formatted,
            filters=prop_filters,
            trunc_func=trunc_func,
            GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
        )
        reference_date_from = self._filter.date_from
        reference_date_to = self._filter.date_from + self._filter.period_increment
        date_from = self._filter.date_from + self._filter.selected_interval * self._filter.period_increment
        date_to = date_from + self._filter.period_increment

        return (
            RETENTION_PEOPLE_SQL.format(
                reference_event_query=reference_event_query,
                target_query=return_query_formatted,
                filters=prop_filters,
                GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
            ),
            {
                "team_id": self._team.pk,
                "start_date": date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if self._filter.period == "Hour" else " 00:00:00")
                ),
                "end_date": date_to.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if self._filter.period == "Hour" else " 00:00:00")
                ),
                "reference_start_date": reference_date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if self._filter.period == "Hour" else " 00:00:00")
                ),
                "reference_end_date": reference_date_to.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if self._filter.period == "Hour" else " 00:00:00")
                ),
                "offset": self._filter.offset,
                **target_params,
                **return_params,
                **prop_filter_params,
            },
        )


class ClickhouseRetentionActorsByPeriod(ActorBaseQuery):
    _filter: RetentionFilter

    def __init__(self, team: Team, filter: RetentionFilter):
        super().__init__(team, filter)

    @cached_property
    def is_aggregating_by_groups(self) -> bool:
        return self._filter.aggregation_group_type_index is not None

    def actor_query(self) -> Tuple[str, Dict]:
        period = self._filter.period
        is_first_time_retention = self._filter.retention_type == RETENTION_FIRST_TIME
        trunc_func = get_trunc_func_ch(period)
        prop_filters, prop_filter_params = parse_prop_clauses(self._filter.properties)

        target_query, target_params = _get_condition(self._filter.target_entity, table="e")
        target_query_formatted = "AND {target_query}".format(target_query=target_query)
        return_query, return_params = _get_condition(self._filter.returning_entity, table="e", prepend="returning")
        return_query_formatted = "AND {return_query}".format(return_query=return_query)
        first_event_sql = (
            REFERENCE_EVENT_UNIQUE_PEOPLE_PER_PERIOD_SQL
            if is_first_time_retention
            else REFERENCE_EVENT_PEOPLE_PER_PERIOD_SQL
        ).format(
            target_query=target_query_formatted,
            filters=prop_filters,
            trunc_func=trunc_func,
            GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
        )
        default_event_query = (
            DEFAULT_REFERENCE_EVENT_UNIQUE_PEOPLE_PER_PERIOD_SQL
            if is_first_time_retention
            else DEFAULT_REFERENCE_EVENT_PEOPLE_PER_PERIOD_SQL
        ).format(
            target_query=target_query_formatted,
            filters=prop_filters,
            trunc_func=trunc_func,
            GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
        )

        date_from = self._filter.date_from + self._filter.selected_interval * self._filter.period_increment
        date_to = self._filter.date_to

        # NOTE: I'm using `Any` here to avoid typing issues when trying to iterate.
        return (
            RETENTION_PEOPLE_PER_PERIOD_SQL.format(
                returning_query=return_query_formatted,
                filters=prop_filters,
                first_event_sql=first_event_sql,
                first_event_default_sql=default_event_query,
                trunc_func=trunc_func,
                GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
            ),
            {
                "team_id": self._team.pk,
                "start_date": date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if self._filter.period == "Hour" else " 00:00:00")
                ),
                "end_date": date_to.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if self._filter.period == "Hour" else " 00:00:00")
                ),
                "offset": self._filter.offset,
                "limit": 100,
                "period": period,
                **target_params,
                **return_params,
                **prop_filter_params,
            },
        )
