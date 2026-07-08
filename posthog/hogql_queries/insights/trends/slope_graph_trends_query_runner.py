from datetime import datetime

from posthog.schema import (
    BaseMathType,
    ChartDisplayType,
    FilterLogicalOperator,
    HogQLPropertyFilter,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    TrendsFilter,
    TrendsQuery,
    TrendsQueryResponse,
)

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner

# Active-users maths compute each bucket from a trailing window, so they need the days *between* the
# two end buckets — the two-bucket scan restriction can't be applied without starving the lookback.
_ACTIVE_USERS_MATHS = (BaseMathType.WEEKLY_ACTIVE, BaseMathType.MONTHLY_ACTIVE)


def _needs_full_scan(query: TrendsQuery) -> bool:
    return any(getattr(s, "math", None) in _ACTIVE_USERS_MATHS for s in query.series)


def _keep_first_and_last_bucket(result: dict) -> None:
    """Keep only the first and last bucket of a trends series — the slope's two points."""
    for key in ("data", "labels", "days"):
        values = result.get(key)
        if isinstance(values, list) and len(values) > 2:
            result[key] = [values[0], values[-1]]


class SlopeGraphTrendsQueryRunner(TrendsQueryRunner):
    """Renders the change between the first and last interval bucket of the selected range.

    A slope shows two points: the value of the first group and the value of the last group, at the
    chosen interval (day/week/month). It runs the ordinary trends time series once — reusing every
    math type, breakdown and filter — but restricts the scan to the first and last bucket's date
    windows, so ClickHouse only reads those two buckets instead of the whole range. The series still
    zero-fills the buckets in between; we slice them off. A range spanning a single bucket yields a
    one-point series, which the frontend drops (there's no slope to draw). The last bucket is shown
    as-is even when it is the current, still-accumulating period; the frontend dashes that last segment,
    mirroring the line chart. Because it has its own display type it caches under its own key.
    """

    def _calculate(self) -> TrendsQueryResponse:
        series_query = self.query.model_copy(deep=True)
        # The two ends *are* the comparison — don't also overlay the prior period.
        series_query.compareFilter = None
        if series_query.trendsFilter is None:
            series_query.trendsFilter = TrendsFilter()
        # Compute the interval series in one query; we slice it to its ends below.
        series_query.trendsFilter.display = ChartDisplayType.ACTIONS_LINE_GRAPH
        # Smoothing is a trailing-window moving average — like active-users math it reads the buckets
        # the scan restriction drops, and it's meaningless on a two-point slope anyway. Clear it.
        series_query.trendsFilter.smoothingIntervals = None
        # Read only the two end buckets, not everything between them — ANDed alongside the query's
        # own filters so a filtered (e.g. shared) slope keeps them rather than going unfiltered.
        # Active-users maths need the days between the buckets for their trailing window, so they skip
        # the restriction and scan the full range (still sliced to two points below).
        if not _needs_full_scan(series_query):
            existing = series_query.properties
            end_buckets_filter = self._end_buckets_filter()
            if isinstance(existing, PropertyGroupFilter):
                # Wrap the existing group and the bucket filter under a new AND so the saved filters
                # are preserved, never replaced.
                series_query.properties = PropertyGroupFilter(
                    type=FilterLogicalOperator.AND_,
                    values=[
                        PropertyGroupFilterValue(**existing.model_dump()),
                        PropertyGroupFilterValue(type=FilterLogicalOperator.AND_, values=[end_buckets_filter]),
                    ],
                )
            else:
                series_query.properties = [*(existing or []), end_buckets_filter]

        response = TrendsQueryRunner(
            query=series_query,
            team=self.team,
            timings=self.timings,
            limit_context=self.limit_context,
            modifiers=self.modifiers,
            user=self.user,
        ).calculate()

        # Whether the last bucket is the current, still-accumulating period — computed once here so
        # the insight and the MCP both forward it rather than each re-deriving it on the frontend.
        incomplete_end = self._last_bucket_is_current()
        for result in response.results or []:
            _keep_first_and_last_bucket(result)
            result["incomplete_end"] = incomplete_end
        return response

    def _last_bucket_is_current(self) -> bool:
        last_start = self.query_date_range.align_with_interval(self.query_date_range.date_to())
        next_start = last_start + self.query_date_range.interval_relativedelta()
        now = self.query_date_range.now_with_timezone
        return last_start <= now < next_start

    def _end_buckets_filter(self) -> HogQLPropertyFilter:
        """Restrict the scan to the first and last interval bucket, aligned to the runner's own
        bucketing so the kept events land in exactly the first and last GROUP BY bucket."""
        date_from = self.query_date_range.date_from()
        date_to = self.query_date_range.date_to()
        first_start = self.query_date_range.align_with_interval(date_from)
        last_start = self.query_date_range.align_with_interval(date_to)
        first_end = first_start + self.query_date_range.interval_relativedelta()
        tz = self.team.timezone

        def lit(value: datetime) -> str:
            return f"toDateTime('{value.strftime('%Y-%m-%d %H:%M:%S')}', '{tz}')"

        expr = (
            f"(timestamp >= {lit(first_start)} and timestamp < {lit(first_end)}) "
            f"or (timestamp >= {lit(last_start)} and timestamp <= {lit(date_to)})"
        )
        return HogQLPropertyFilter(key=expr)
