from typing import Any, Dict, List

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from ee.clickhouse.queries.sessions.average import ClickhouseSessionsAvg
from ee.clickhouse.queries.sessions.distribution import ClickhouseSessionsDist
from ee.clickhouse.queries.sessions.list import SESSIONS_LIST_DEFAULT_LIMIT, ClickhouseSessionsList
from posthog.constants import SESSION_AVG, SESSION_DIST
from posthog.models import Filter, Team
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.base import BaseQuery, convert_to_comparison, determine_compared_filter
from posthog.utils import relative_date_parse


class ClickhouseSessions(BaseQuery, ClickhouseSessionsList, ClickhouseSessionsAvg, ClickhouseSessionsDist):
    def _set_default_dates(self, filter: Filter) -> None:
        # format default dates
        if filter.session_type != SESSION_AVG and filter.session_type != SESSION_DIST:
            if not filter._date_from:
                filter._date_from = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            if not filter._date_to and filter.date_from:
                filter._date_to = filter.date_from + relativedelta(days=1)
        else:
            if not filter._date_from:
                filter._date_from = relative_date_parse("-7d")
            if not filter._date_to:
                filter._date_to = timezone.now()

    def run(self, filter: SessionsFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        limit = kwargs.get("limit", SESSIONS_LIST_DEFAULT_LIMIT)
        offset = kwargs.get("offset", 0)

        result: List = []

        self._set_default_dates(filter)
        if filter.session_type == SESSION_AVG:

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

        elif filter.session_type == SESSION_DIST:
            result = self.calculate_dist(filter, team)
        else:
            result = self.calculate_list(filter, team, limit, offset)

        return result
