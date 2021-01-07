from django.utils import timezone

from ee.clickhouse.queries.trends.breakdown import ClickhouseTrendsBreakdown
from ee.clickhouse.queries.trends.lifecycle import ClickhouseLifecycle
from ee.clickhouse.queries.trends.normal import ClickhouseTrendsNormal
from posthog.models.filters import Filter
from posthog.queries.trends import Trends
from posthog.utils import relative_date_parse


class ClickhouseTrends(ClickhouseTrendsNormal, ClickhouseTrendsBreakdown, ClickhouseLifecycle, Trends):
    def _set_default_dates(self, filter: Filter, team_id: int) -> Filter:
        data = {}
        if not filter._date_from:
            data.update({"date_from": relative_date_parse("-7d")})
        if not filter._date_to:
            data.update({"date_to": timezone.now()})
        if data:
            return Filter(data={**filter._data, **data})
        return filter
