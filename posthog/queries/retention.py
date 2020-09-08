import datetime
from datetime import timedelta
from typing import Any, Dict, List

from posthog.models import Event, Filter, Team
from posthog.queries.base import BaseQuery


class Retention(BaseQuery):
    def calculate_retention(self, filter: Filter, team: Team, total_days=11):

        date_from: datetime.datetime = filter.date_from  # type: ignore
        filter._date_to = (date_from + timedelta(days=total_days)).isoformat()
        labels_format = "%a. %-d %B"
        resultset = Event.objects.query_retention(filter, team)

        result = [
            {
                "values": [
                    resultset.get((first_day, day), {"count": 0, "people": []}) for day in range(total_days - first_day)
                ],
                "label": "Day {}".format(first_day),
                "date": (date_from + timedelta(days=first_day)).strftime(labels_format),
            }
            for first_day in range(total_days)
        ]

        return result

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return self.calculate_retention(filter=filter, team=team, total_days=kwargs.get("total_days", 11),)
