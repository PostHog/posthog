from typing import Any, Dict, List, Union

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from ee.clickhouse.queries.sessions.average import ClickhouseSessionsAvg
from ee.clickhouse.queries.sessions.distribution import ClickhouseSessionsDist
from posthog.constants import SESSION_AVG, SESSION_DIST
from posthog.models import Team
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.base import BaseQuery, convert_to_comparison, determine_compared_filter
from posthog.utils import relative_date_parse


def set_default_dates(filter: SessionsFilter) -> SessionsFilter:
    data = {}
    if filter.session != SESSION_AVG and filter.session != SESSION_DIST:
        date_from = filter.date_from
        if not filter._date_from:
            date_from = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        data.update({"date_from": date_from})
        if not filter._date_to:
            data.update({"date_to": date_from + relativedelta(days=1)})
    else:
        if not filter._date_from:
            data.update({"date_from": relative_date_parse("-7d")})
        if not filter._date_to:
            data.update({"date_to": timezone.now()})
    return SessionsFilter(data={**filter._data, **data, "user_id": filter.user_id})


class ClickhouseSessions(BaseQuery, ClickhouseSessionsAvg, ClickhouseSessionsDist):
    def run(self, filter: SessionsFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        result: List = []

        filter = set_default_dates(filter)
        if filter.session == SESSION_AVG:
            if filter.compare:
                current_response = self.calculate_avg(filter, team)
                parsed_response = convert_to_comparison(current_response, filter, "current")
                result.extend(parsed_response)

                compared_filter = determine_compared_filter(filter)
                compared_result = self.calculate_avg(compared_filter, team)
                compared_res = convert_to_comparison(compared_result, filter, "previous")
                result.extend(compared_res)
            else:
                result = self.calculate_avg(filter, team)

        elif filter.session == SESSION_DIST:
            result = self.calculate_dist(filter, team)

        return result
