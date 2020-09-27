from datetime import datetime, timedelta
from typing import Any, Dict, List

from ee.clickhouse.client import ch_client
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.sql.retention import RETENTION_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.team import Team
from posthog.queries.base import BaseQuery


class ClickhouseRetention(BaseQuery):
    def calculate_retention(self, filter: Filter, team: Team, total_days: int) -> List[Dict[str, Any]]:
        if filter.date_from:
            date_from = filter.date_from
            date_to = date_from + timedelta(days=total_days)
        else:
            date_to = datetime.now()
            date_from = date_to - timedelta(days=total_days)

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

        result = ch_client.execute(
            RETENTION_SQL.format(
                target_query=target_query,
                filters="{filters}".format(filters=prop_filters) if filter.properties else "",
            ),
            {
                "team_id": team.pk,
                "start_date": date_from.strftime("%Y-%m-%d"),
                "end_date": date_to.strftime("%Y-%m-%d"),
                **prop_filter_params,
                **target_params,
            },
        )

        result_dict = {}

        for res in result:
            result_dict.update({(res[0], res[1]): {"count": res[2], "people": []}})

        labels_format = "%a. %-d %B"
        parsed = [
            {
                "values": [
                    result_dict.get((first_day, day), {"count": 0, "people": []})
                    for day in range(total_days - first_day)
                ],
                "label": "Day {}".format(first_day),
                "date": (date_from + timedelta(days=first_day)).strftime(labels_format),
            }
            for first_day in range(total_days)
        ]

        return parsed

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        total_days = kwargs.get("total_days", 11)
        return self.calculate_retention(filter, team, total_days)
