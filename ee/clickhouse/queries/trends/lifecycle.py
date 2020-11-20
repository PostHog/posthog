from typing import Any, Dict, List

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
from posthog.models.filters import Filter
from posthog.models.team import Team


class ClickhouseLifecycle:
    def get_interval(self, interval: str) -> relativedelta:
        if interval == "hour":
            return relativedelta(hours=1)
        elif interval == "minute":
            return relativedelta(minutes=1)
        elif interval == "day":
            return relativedelta(day=1)
        elif interval == "week":
            return relativedelta(weeks=1)
        elif interval == "month":
            return relativedelta(months=1)
        else:
            raise ValueError("{interval} not supported")

    def _serialize_lifecycle(self, entity: Entity, filter: Filter, team_id: int) -> List[Dict[str, Any]]:

        interval = filter.interval or "day"
        num_intervals, seconds_in_interval = get_time_diff(interval, filter.date_from, filter.date_to)
        interval_increment = self.get_interval(interval)
        trunc_func = get_interval_annotation_ch(interval)
        event_query = ""
        event_params = {}

        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)

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
            LIFECYCLE_SQL.format(interval="1 DAY", trunc_func=trunc_func, event_query=event_query),
            {
                "team_id": team_id,
                "date_from": parsed_date_from,
                "prev_date_from": "2020-01-11 00:00:00",
                "date_to": parsed_date_to,
                "num_intervals": num_intervals,
                "seconds_in_interval": seconds_in_interval,
                **event_params,
            },
        )

        res = []
        for val in result:
            label = "{} - {}".format(entity.name, val[2])
            additional_values = {"label": label, "status": val[2]}
            parsed_result = parse_response(val, filter, additional_values)
            res.append(parsed_result)
        print(res)
        return res
