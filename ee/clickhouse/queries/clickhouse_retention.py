from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple, Union

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.sql.retention import RETENTION_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.team import Team
from posthog.queries.base import BaseQuery

PERIOD_TRUNC_HOUR = "toStartOfHour"
PERIOD_TRUNC_DAY = "toStartOfDay"
PERIOD_TRUNC_WEEK = "toStartOfWeek"
PERIOD_TRUNC_MONTH = "toStartOfMonth"


class ClickhouseRetention(BaseQuery):
    def calculate_retention(self, filter: Filter, team: Team, total_intervals: int) -> List[Dict[str, Any]]:

        period = filter.period or "Day"

        tdelta, trunc_func = self._determineTimedelta(total_intervals, period)

        if filter.date_from:
            date_from = filter.date_from
            date_to = date_from + tdelta
        else:
            date_to = timezone.now()
            date_from = date_to - tdelta

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
            action_query, target_params = format_action_filter(action)
            target_query = "AND e.uuid IN ({})".format(action_query)
        elif target_entity.type == TREND_FILTER_TYPE_EVENTS:
            target_query = "AND e.event = %(target_event)s"
            target_params = {"target_event": target_entity.id}

        result = sync_execute(
            RETENTION_SQL.format(
                target_query=target_query,
                filters="{filters}".format(filters=prop_filters) if filter.properties else "",
                trunc_func=trunc_func,
            ),
            {
                "team_id": team.pk,
                "start_date": date_from.strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": date_to.strftime("%Y-%m-%d %H:%M:%S"),
                **prop_filter_params,
                **target_params,
                "period": period,
            },
        )

        result_dict = {}

        for res in result:
            result_dict.update({(res[0], res[1]): {"count": res[2], "people": []}})

        if period == "Week":
            date_from = date_from - timedelta(days=date_from.isoweekday() % 7)

        labels_format = "%a. %-d %B"
        hourly_format = "%-H:%M %p"
        parsed = [
            {
                "values": [
                    result_dict.get((first_day, day), {"count": 0, "people": []})
                    for day in range(total_intervals - first_day)
                ],
                "label": "Day {}".format(first_day),
                "date": (date_from + self._determineTimedelta(first_day, period)[0]).strftime(
                    labels_format + (hourly_format if period == "Hour" else "")
                ),
            }
            for first_day in range(total_intervals)
        ]

        return parsed

    def _determineTimedelta(self, total_intervals: int, period: str) -> Tuple[Union[timedelta, relativedelta], str]:
        if period == "Hour":
            return timedelta(hours=total_intervals), PERIOD_TRUNC_HOUR
        elif period == "Week":
            return timedelta(weeks=total_intervals), PERIOD_TRUNC_WEEK
        elif period == "Day":
            return timedelta(days=total_intervals), PERIOD_TRUNC_DAY
        elif period == "Month":
            return relativedelta(months=total_intervals), PERIOD_TRUNC_MONTH
        else:
            raise ValueError(f"Period {period} is unsupported.")

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        total_intervals = kwargs.get("total_intervals", 11)
        return self.calculate_retention(filter, team, total_intervals)
