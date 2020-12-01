from typing import Any, Dict, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.person import ClickhousePersonSerializer
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.sql.retention.retention import (
    INITIAL_INTERVAL_SQL,
    REFERENCE_EVENT_SQL,
    REFERENCE_EVENT_UNIQUE_SQL,
    RETENTION_PEOPLE_SQL,
    RETENTION_SQL,
)
from posthog.constants import RETENTION_FIRST_TIME, TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS, TRENDS_LINEAR
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filters import Filter, RetentionFilter
from posthog.models.team import Team
from posthog.queries.retention import Retention

PERIOD_TRUNC_HOUR = "toStartOfHour"
PERIOD_TRUNC_DAY = "toStartOfDay"
PERIOD_TRUNC_WEEK = "toStartOfWeek"
PERIOD_TRUNC_MONTH = "toStartOfMonth"


class ClickhouseRetention(Retention):
    def _execute_sql(self, filter: RetentionFilter, team: Team,) -> Dict[Tuple[int, int], Dict[str, Any]]:
        period = filter.period
        prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, team.pk)
        target_entity = filter.target_entity
        returning_entity = filter.returning_entity
        is_first_time_retention = filter.retention_type == RETENTION_FIRST_TIME
        date_from = filter.date_from
        date_to = filter.date_to

        target_query = ""
        target_params: Dict = {}
        trunc_func = self._get_trunc_func_ch(period)

        target_query, target_params = self._get_condition(target_entity, table="e")
        returning_query, returning_params = self._get_condition(returning_entity, table="e", prepend="returning")

        target_query_formatted = "AND {target_query}".format(target_query=target_query)
        returning_query_formatted = "AND {returning_query}".format(returning_query=returning_query)

        reference_event_sql = (REFERENCE_EVENT_UNIQUE_SQL if is_first_time_retention else REFERENCE_EVENT_SQL).format(
            target_query=target_query_formatted, filters=prop_filters, trunc_func=trunc_func,
        )

        target_condition, _ = self._get_condition(target_entity, table="reference_event")
        if is_first_time_retention:
            target_condition = target_condition.replace("reference_event.uuid", "reference_event.min_uuid")
            target_condition = target_condition.replace("reference_event.event", "reference_event.min_event")
        returning_condition, _ = self._get_condition(returning_entity, table="event", prepend="returning")
        result = sync_execute(
            RETENTION_SQL.format(
                target_query=target_query_formatted,
                returning_query=returning_query_formatted,
                filters=prop_filters,
                trunc_func=trunc_func,
                extra_union="UNION ALL {} ".format(reference_event_sql),
                reference_event_sql=reference_event_sql,
                target_condition=target_condition,
                returning_condition=returning_condition,
            ),
            {
                "team_id": team.pk,
                "start_date": date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "end_date": date_to.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "reference_start_date": date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "reference_end_date": (
                    (date_from + filter.period_increment) if filter.display == TRENDS_LINEAR else date_to
                ).strftime("%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")),
                **prop_filter_params,
                **target_params,
                **returning_params,
                "period": period,
            },
        )

        initial_interval_result = sync_execute(
            INITIAL_INTERVAL_SQL.format(reference_event_sql=reference_event_sql),
            {
                "team_id": team.pk,
                "start_date": date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "end_date": date_to.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "reference_start_date": date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "reference_end_date": (
                    (date_from + filter.period_increment) if filter.display == TRENDS_LINEAR else date_to
                ).strftime("%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")),
                **prop_filter_params,
                **target_params,
                **returning_params,
                "period": period,
            },
        )

        result_dict = {}
        for initial_res in initial_interval_result:
            result_dict.update({(initial_res[0], 0): {"count": initial_res[1], "people": []}})

        for res in result:
            result_dict.update({(res[0], res[1]): {"count": res[2], "people": []}})

        return result_dict

    def _get_condition(self, target_entity: Entity, table: str, prepend: str = "") -> Tuple[str, Dict]:
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

    def _get_trunc_func_ch(self, period: str) -> str:
        if period == "Hour":
            return PERIOD_TRUNC_HOUR
        elif period == "Week":
            return PERIOD_TRUNC_WEEK
        elif period == "Day":
            return PERIOD_TRUNC_DAY
        elif period == "Month":
            return PERIOD_TRUNC_MONTH
        else:
            raise ValueError(f"Period {period} is unsupported.")

    def _retrieve_people(
        self, filter: RetentionFilter, team: Team, offset,
    ):
        period = filter.period
        is_first_time_retention = filter.retention_type == RETENTION_FIRST_TIME
        trunc_func = self._get_trunc_func_ch(period)
        prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, team.pk)

        returning_entity = filter.returning_entity if filter.selected_interval > 0 else filter.target_entity
        target_query, target_params = self._get_condition(filter.target_entity, table="e")
        target_query_formatted = "AND {target_query}".format(target_query=target_query)
        return_query, return_params = self._get_condition(returning_entity, table="e", prepend="returning")
        return_query_formatted = "AND {return_query}".format(return_query=return_query)

        reference_event_query = (REFERENCE_EVENT_UNIQUE_SQL if is_first_time_retention else REFERENCE_EVENT_SQL).format(
            target_query=target_query_formatted, filters=prop_filters, trunc_func=trunc_func,
        )
        reference_date_from = filter.date_from
        reference_date_to = filter.date_from + filter.period_increment
        date_from = filter.date_from + filter.selected_interval * filter.period_increment
        date_to = date_from + filter.period_increment

        result = sync_execute(
            RETENTION_PEOPLE_SQL.format(
                reference_event_query=reference_event_query, target_query=return_query_formatted, filters=prop_filters
            ),
            {
                "team_id": team.pk,
                "start_date": date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "end_date": date_to.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "reference_start_date": reference_date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "reference_end_date": reference_date_to.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "offset": offset,
                **target_params,
                **return_params,
                **prop_filter_params,
            },
        )
        serialized = ClickhousePersonSerializer(result, many=True).data
        return serialized
