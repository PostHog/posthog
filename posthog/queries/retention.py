from posthog.models import Filter, Team, Entity, Event
from typing import Optional
import datetime
from datetime import timedelta


class Retention:
    def calculate_retention(self, filter: Filter, team: Team, start_entity: Optional[Entity] = None, total_days=11):
        date_from: datetime.datetime = filter.date_from  # type: ignore
        filter._date_to = (date_from + timedelta(days=total_days)).isoformat()
        labels_format = "%a. %-d %B"
        resultset = Event.objects.query_retention(filter, team, start_entity=start_entity)

        result = {
            "data": [
                {
                    "values": [
                        resultset.get((first_day, day), {"count": 0, "people": []})
                        for day in range(total_days - first_day)
                    ],
                    "label": "Day {}".format(first_day),
                    "date": (date_from + timedelta(days=first_day)).strftime(labels_format),
                }
                for first_day in range(total_days)
            ]
        }

        return result

    def run(self, filter: Filter, team: Team):
        return self.calculate_retention(
            filter=filter, team=team, start_entity=filter.entities[0] if len(filter.entities) > 0 else None
        )
