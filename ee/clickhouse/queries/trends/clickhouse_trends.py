from django.utils import timezone

from ee.clickhouse.queries.trends.breakdown import ClickhouseTrendsBreakdown
from ee.clickhouse.queries.trends.normal import ClickhouseTrendsNormal
from posthog.models.filters import Filter
from posthog.queries.trends import Trends
from posthog.utils import relative_date_parse


class ClickhouseTrends(ClickhouseTrendsNormal, ClickhouseTrendsBreakdown, Trends):
    def _set_default_dates(self, filter: Filter, team_id: int) -> None:
        if not filter._date_from:
            filter._date_from = relative_date_parse("-7d")
        if not filter._date_to:
            filter._date_to = timezone.now()
