import datetime
from datetime import timedelta
from typing import Any, Dict, List, Union

from dateutil.relativedelta import relativedelta

from posthog.models import Event, Filter, Team
from posthog.queries.base import BaseQuery


class Retention(BaseQuery):
    def calculate_retention(self, filter: Filter, team: Team, total_intervals=11):
        def _determineTimedelta(total_intervals: int, period: str) -> Union[timedelta, relativedelta]:
            if period == "Hour":
                return timedelta(hours=total_intervals)
            elif period == "Week":
                return timedelta(weeks=total_intervals)
            elif period == "Month":
                return relativedelta(months=total_intervals)
            elif period == "Day":
                return timedelta(days=total_intervals)
            else:
                raise ValueError(f"Period {period} is unsupported.")

        period = filter.period
        date_from: datetime.datetime = filter.date_from  # type: ignore
        filter._date_to = (date_from + _determineTimedelta(total_intervals, period)).isoformat()
        labels_format = "%a. %-d %B"
        hourly_format = "%-H:%M %p"
        resultset = Event.objects.query_retention(filter, team)

        result = [
            {
                "values": [
                    resultset.get((first_day, day), {"count": 0, "people": []})
                    for day in range(total_intervals - first_day)
                ],
                "label": "Day {}".format(first_day),
                "date": (date_from + _determineTimedelta(first_day, period)).strftime(
                    labels_format + (hourly_format if period == "Hour" else "")
                ),
            }
            for first_day in range(total_intervals)
        ]

        return result

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return self.calculate_retention(filter=filter, team=team, total_intervals=kwargs.get("total_intervals", 11),)
