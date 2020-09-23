from datetime import datetime, timedelta
from typing import Any, Dict, List

from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.retention import RETENTION_SQL
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

        result = ch_client.execute(
            RETENTION_SQL,
            {
                "team_id": team.pk,
                "start_date": date_from.strftime("%Y-%m-%d"),
                "end_date": date_to.strftime("%Y-%m-%d"),
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
