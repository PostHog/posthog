from datetime import timedelta
from typing import Dict

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.sql.retention.retention import RETENTION_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.queries.retention import Retention

PERIOD_TRUNC_HOUR = "toStartOfHour"
PERIOD_TRUNC_DAY = "toStartOfDay"
PERIOD_TRUNC_WEEK = "toStartOfWeek"
PERIOD_TRUNC_MONTH = "toStartOfMonth"


class ClickhouseRetention(Retention):
    def _get_trunc_func(self, period: str) -> str:
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

    def _execute_sql(self, filter: Filter, team):
        period = filter.period
        date_from = filter.date_from
        date_to = filter.date_to
        prop_filters, prop_filter_params = parse_prop_clauses("uuid", filter.properties, team)

        target_query = ""
        target_params: Dict = {}

        target_entity = (
            Entity({"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS})
            if not filter.target_entity
            else filter.target_entity
        )
        if target_entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=target_entity.id)
            action_query, target_params = format_action_filter(action, use_loop=True)
            target_query = "AND e.uuid IN ({})".format(action_query)
        elif target_entity.type == TREND_FILTER_TYPE_EVENTS:
            target_query = "AND e.event = %(target_event)s"
            target_params = {"target_event": target_entity.id}

        trunc_func = self._get_trunc_func(period)

        if period == "Week":
            date_from = date_from - timedelta(days=date_from.isoweekday() % 7)

        result = sync_execute(
            RETENTION_SQL.format(
                target_query=target_query,
                filters="{filters}".format(filters=prop_filters) if filter.properties else "",
                trunc_func=trunc_func,
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
                "period": period,
            },
        )

        result_dict = {}

        for res in result:
            result_dict.update({(res[0], res[1]): {"count": res[2], "people": []}})

        return result_dict
