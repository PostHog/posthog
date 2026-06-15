from datetime import datetime, timedelta

from posthog.schema import ChartDisplayType, DateRange, ResolvedDateRangeResponse, TrendsFilter, TrendsQueryResponse

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner


class SlopeGraphTrendsQueryRunner(TrendsQueryRunner):
    """Renders the change between the first and last interval of the selected range.

    A slope graph compares two points: the value of the first group and the value of the last group,
    at the chosen interval (day/week/month). Rather than computing the whole time series and keeping
    only its ends, this runs two cheap total-value queries — one per end bucket — and returns one
    two-point series per series/breakdown, however many buckets sit between them. The last bucket is
    shown as-is even when it is the current, still-accumulating period; the frontend dashes that
    endpoint, mirroring the line chart. Because it has its own display type it caches under its own
    key rather than sharing the line graph's expensive result.
    """

    def _calculate(self) -> TrendsQueryResponse:
        date_from = self.query_date_range.date_from()
        date_to = self.query_date_range.date_to()
        resolved_date_range = ResolvedDateRangeResponse(date_from=date_from, date_to=date_to)

        first_bucket_start = self.query_date_range.align_with_interval(date_from)
        last_bucket_start = self.query_date_range.align_with_interval(date_to)
        first_bucket_end = first_bucket_start + self.query_date_range.interval_relativedelta()

        first = self._aggregate_window(first_bucket_start, first_bucket_end - timedelta(microseconds=1))
        last = self._aggregate_window(last_bucket_start, date_to)

        labels = [self._format_bucket(first_bucket_start), self._format_bucket(last_bucket_start)]
        days = [first_bucket_start.strftime("%Y-%m-%d"), last_bucket_start.strftime("%Y-%m-%d")]

        results = self._zip_windows(first.results or [], last.results or [], labels, days)

        timings = (first.timings or []) + (last.timings or [])
        errors = [e for e in (first.error, last.error) if e]

        return TrendsQueryResponse(
            results=results,
            timings=timings or None,
            error=". ".join(errors) if errors else None,
            modifiers=self.modifiers,
            resolved_date_range=resolved_date_range,
        )

    def _format_bucket(self, start: datetime) -> str:
        if self.query_date_range.interval_name == "month":
            return start.strftime("%b %Y")
        if self.query_date_range.interval_name in ("hour", "minute", "second"):
            return start.strftime("%b %d, %Y %H:%M")
        return start.strftime("%b %d, %Y")

    def _aggregate_window(self, start: datetime, end: datetime) -> TrendsQueryResponse:
        """Total value of the metric over a single end bucket, reusing the standard trends path."""
        window_query = self.query.model_copy(deep=True)
        window_query.dateRange = DateRange(date_from=start.isoformat(), date_to=end.isoformat())
        # The two end buckets *are* the comparison — don't also pull in the period before the range.
        window_query.compareFilter = None
        if window_query.trendsFilter is None:
            window_query.trendsFilter = TrendsFilter()
        # A total-value display yields a single aggregated value per series/breakdown.
        window_query.trendsFilter.display = ChartDisplayType.ACTIONS_BAR_VALUE

        runner = TrendsQueryRunner(
            query=window_query,
            team=self.team,
            timings=self.timings,
            limit_context=self.limit_context,
            modifiers=self.modifiers,
            user=self.user,
        )
        return runner.calculate()

    @staticmethod
    def _series_key(result: dict) -> tuple:
        action_order = (result.get("action") or {}).get("order")
        order = action_order if action_order is not None else result.get("order", 0)
        return (order, str(result.get("breakdown_value")))

    def _zip_windows(self, first: list[dict], second: list[dict], labels: list[str], days: list[str]) -> list[dict]:
        by_key_first = {self._series_key(r): r for r in first}
        by_key_second = {self._series_key(r): r for r in second}

        # Preserve the first window's series order, then append any series only present in the second.
        ordered_keys: list[tuple] = []
        seen: set[tuple] = set()
        for r in [*first, *second]:
            key = self._series_key(r)
            if key not in seen:
                ordered_keys.append(key)
                seen.add(key)

        results: list[dict] = []
        for key in ordered_keys:
            a = by_key_first.get(key)
            b = by_key_second.get(key)
            base = a or b
            if base is None:
                continue
            start_value = float(a.get("aggregated_value", 0) or 0) if a else 0.0
            end_value = float(b.get("aggregated_value", 0) or 0) if b else 0.0
            results.append(
                {
                    "data": [start_value, end_value],
                    "labels": labels,
                    "days": days,
                    "count": start_value + end_value,
                    "label": base.get("label"),
                    "breakdown_value": base.get("breakdown_value"),
                    "action": base.get("action"),
                    "filter": base.get("filter"),
                }
            )
        return results
