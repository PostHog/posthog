from datetime import timedelta
from typing import Any, Dict, List, Tuple, Union

import sqlparse
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.queries.trends.util import parse_response
from ee.clickhouse.queries.util import get_interval_annotation_ch, get_time_diff, parse_timestamps
from ee.clickhouse.sql.trends.lifecycle import LIFECYCLE_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.team import Team


class ClickhouseLifecycle:
    def get_interval(self, interval: str) -> Tuple[Union[timedelta, relativedelta], str]:
        if interval == "hour":
            return timedelta(hours=1), "1 HOUR"
        elif interval == "minute":
            return timedelta(minutes=1), "1 MINUTE"
        elif interval == "day":
            return timedelta(days=1), "1 DAY"
        elif interval == "week":
            return timedelta(weeks=1), "1 WEEK"
        elif interval == "month":
            return relativedelta(months=1), "1 MONTH"
        else:
            raise ValueError("{interval} not supported")

    def _serialize_lifecycle(self, entity: Entity, filter: Filter, team_id: int) -> List[Dict[str, Any]]:

        date_from = filter.date_from

        if not date_from:
            raise ValueError("Starting date must be provided")

        interval = filter.interval or "day"
        num_intervals, seconds_in_interval = get_time_diff(interval, filter.date_from, filter.date_to)
        interval_increment, interval_string = self.get_interval(interval)
        trunc_func = get_interval_annotation_ch(interval)
        event_query = ""
        event_params: Dict[str, Any] = {}

        _, _, date_params = parse_timestamps(filter=filter)

        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            try:
                action = Action.objects.get(pk=entity.id)
                event_query, event_params = format_action_filter(action)
            except:
                return []
        else:
            event_query = "event = %(event)s"
            event_params = {"event": entity.id}

        result = sync_execute(
            LIFECYCLE_SQL.format(interval=interval_string, trunc_func=trunc_func, event_query=event_query),
            {
                "team_id": team_id,
                "prev_date_from": (date_from - interval_increment).strftime(
                    "%Y-%m-%d{}".format(
                        " %H:%M:%S" if filter.interval == "hour" or filter.interval == "minute" else " 00:00:00"
                    )
                ),
                "num_intervals": num_intervals,
                "seconds_in_interval": seconds_in_interval,
                **event_params,
                **date_params,
            },
        )

        res = []
        for val in result:
            label = "{} - {}".format(entity.name, val[2])
            additional_values = {"label": label, "status": val[2]}
            parsed_result = parse_response(val, filter, additional_values)
            res.append(parsed_result)

        return res
