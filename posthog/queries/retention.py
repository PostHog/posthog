from datetime import timedelta
from typing import Any, Dict, List, Tuple, Union

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now

from posthog.models import Event, Filter, Team
from posthog.queries.base import BaseQuery


class Retention(BaseQuery):
    def calculate_retention(self, filter: Filter, team: Team, total_intervals=11):
        period = filter.period or "Day"
        tdelta, t1 = self.determineTimedelta(total_intervals, period)
        filter._date_to = ((filter.date_to if filter.date_to else now()) + t1).isoformat()

        if period == "Hour":
            date_to = filter.date_to if filter.date_to else now()
            date_from = date_to - tdelta
        else:

            date_to = (filter.date_to if filter.date_to else now()).replace(hour=0, minute=0, second=0, microsecond=0)
            date_from = date_to - tdelta

        filter._date_from = date_from.isoformat()
        filter._date_to = date_to.isoformat()

        resultset = self._execute_sql(filter, team)

        result = [
            {
                "values": [
                    resultset.get((first_day, day), {"count": 0, "people": []})
                    for day in range(total_intervals - first_day)
                ],
                "label": "{} {}".format(period, first_day),
                "date": (date_from + self.determineTimedelta(first_day, period)[0]),
            }
            for first_day in range(total_intervals)
        ]

        return result

    def _execute_sql(self, filter, team):
        return Event.objects.query_retention(filter, team)

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return self.calculate_retention(filter=filter, team=team, total_intervals=kwargs.get("total_intervals", 11),)

    def determineTimedelta(
        self, total_intervals: int, period: str
    ) -> Tuple[Union[timedelta, relativedelta], Union[timedelta, relativedelta]]:
        if period == "Hour":
            return timedelta(hours=total_intervals), timedelta(hours=1)
        elif period == "Week":
            return timedelta(weeks=total_intervals), timedelta(weeks=1)
        elif period == "Month":
            return relativedelta(months=total_intervals), relativedelta(months=1)
        elif period == "Day":
            return timedelta(days=total_intervals), timedelta(days=1)
        else:
            raise ValueError(f"Period {period} is unsupported.")
