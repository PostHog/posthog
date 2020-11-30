import datetime
from typing import Any, Dict, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.sql.retention.retention import REFERENCE_EVENT_SQL, REFERENCE_EVENT_UNIQUE_SQL, RETENTION_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.team import Team
from posthog.queries.retention import Retention

PERIOD_TRUNC_HOUR = "toStartOfHour"
PERIOD_TRUNC_DAY = "toStartOfDay"
PERIOD_TRUNC_WEEK = "toStartOfWeek"
PERIOD_TRUNC_MONTH = "toStartOfMonth"


class ClickhouseRetention(Retention):
    def _execute_sql(
        self,
        filter: Filter,
        date_from: datetime.datetime,
        date_to: datetime.datetime,
        target_entity: Entity,
        returning_entity: Entity,
        is_first_time_retention: bool,
        team: Team,
    ) -> Dict[Tuple[int, int], Dict[str, Any]]:
        period = filter.period
        prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, team.pk)

        target_query = ""
        target_params: Dict = {}
        trunc_func = self._get_trunc_func_ch(period)

        if target_entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=target_entity.id)
            action_query, target_params = format_action_filter(action, use_loop=True)
            target_query = "AND e.uuid IN ({})".format(action_query)
        elif target_entity.type == TREND_FILTER_TYPE_EVENTS:
            target_query = "AND e.event = %(target_event)s"
            target_params = {"target_event": target_entity.id}

        target_query, target_params = self._get_condition(target_entity)
        returning_query, returning_params = self._get_condition(returning_entity, "returning")

        target_query_formatted = (
            "AND {target_query}".format(target_query=target_query)
            if is_first_time_retention
            else "AND ({target_query} OR {returning_query})".format(
                target_query=target_query, returning_query=returning_query
            )
        )
        returning_query_formatted = (
            "AND {returning_query}".format(returning_query=returning_query)
            if is_first_time_retention
            else "AND ({target_query} OR {returning_query})".format(
                target_query=target_query, returning_query=returning_query
            )
        )

        reference_event_sql = (REFERENCE_EVENT_UNIQUE_SQL if is_first_time_retention else REFERENCE_EVENT_SQL).format(
            target_query=target_query_formatted, filters=prop_filters, trunc_func=trunc_func,
        )
        result = sync_execute(
            RETENTION_SQL.format(
                target_query=target_query_formatted,
                returning_query=returning_query_formatted,
                filters=prop_filters,
                trunc_func=trunc_func,
                extra_union="UNION ALL {}".format(reference_event_sql) if is_first_time_retention else "",
                reference_event_sql=reference_event_sql,
            ),
            {
                "team_id": team.pk,
                "start_date": date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "end_date": date_to.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                **prop_filter_params,
                **target_params,
                **returning_params,
                "period": period,
            },
        )

        result_dict = {}

        for res in result:
            result_dict.update({(res[0], res[1]): {"count": res[2], "people": []}})

        return result_dict

    def _get_condition(self, target_entity: Entity, prepend: str = "") -> Tuple[str, Dict]:
        if target_entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=target_entity.id)
            action_query, params = format_action_filter(action, prepend=prepend, use_loop=True)
            condition = "e.uuid IN ({})".format(action_query)
        elif target_entity.type == TREND_FILTER_TYPE_EVENTS:
            condition = "e.event = %({}_event)s".format(prepend)
            params = {"{}_event".format(prepend): target_entity.id}
        else:
            condition = "e.event = %({}_event)s".format(prepend)
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
