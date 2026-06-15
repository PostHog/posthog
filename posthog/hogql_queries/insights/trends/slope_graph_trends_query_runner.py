from datetime import datetime, timedelta

from posthog.schema import ChartDisplayType, DateRange, ResolvedDateRangeResponse, TrendsFilter, TrendsQueryResponse

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner


def _format_endpoint(value: datetime) -> str:
    return value.strftime("%b %d, %Y")


class SlopeGraphTrendsQueryRunner(TrendsQueryRunner):
    """Renders the change between the two ends of the selected range.

    A slope graph only needs two points, so instead of computing the full time series and keeping
    only the endpoints, this aggregates the metric over the first half and the second half of the
    range — two cheap total-value queries — and returns one two-point series per series/breakdown.
    The split itself is day-based; the interval (day/week/month) only decides what counts as the
    current incomplete period that is trimmed off the end by default (see `_effective_date_to`).
    Because it has its own display type it caches under its own key rather than sharing the line
    graph's expensive result.
    """

    def _calculate(self) -> TrendsQueryResponse:
        date_from = self.query_date_range.date_from()
        date_to = self._effective_date_to(date_from)
        resolved_date_range = ResolvedDateRangeResponse(date_from=date_from, date_to=date_to)

        first_window_end, second_window_start = self._split_on_day_boundary(date_from, date_to)

        first = self._aggregate_window(date_from, first_window_end)
        second = self._aggregate_window(second_window_start, date_to)

        labels = [
            f"{_format_endpoint(date_from)} – {_format_endpoint(first_window_end)}",
            f"{_format_endpoint(second_window_start)} – {_format_endpoint(date_to)}",
        ]
        days = [date_from.strftime("%Y-%m-%d"), second_window_start.strftime("%Y-%m-%d")]

        results = self._zip_windows(first.results or [], second.results or [], labels, days)

        timings = (first.timings or []) + (second.timings or [])
        errors = [e for e in (first.error, second.error) if e]

        return TrendsQueryResponse(
            results=results,
            timings=timings or None,
            error=". ".join(errors) if errors else None,
            modifiers=self.modifiers,
            resolved_date_range=resolved_date_range,
        )

    def _effective_date_to(self, date_from: datetime) -> datetime:
        """`date_to`, trimmed to the last complete period unless the user opted in to the current one.

        The trends path always extends `date_to` to the current, still-accumulating period, which on a
        slope drags the end value down and can read as a fall (e.g. today is only part-way counted).
        By default we end at the last complete period instead; `slopeIncludeIncompletePeriod` keeps the
        partial one. Trimming the range *before* splitting keeps the two halves balanced. A range that
        is wholly within the current period is left untouched rather than trimmed to nothing.
        """
        date_to = self.query_date_range.date_to()
        trends_filter = self.query.trendsFilter
        if trends_filter is not None and trends_filter.slopeIncludeIncompletePeriod:
            return date_to

        current_period_start = self.query_date_range.align_with_interval(self.query_date_range.now_with_timezone)
        if date_to < current_period_start:
            return date_to

        last_complete_period_end = current_period_start - timedelta(microseconds=1)
        if last_complete_period_end <= date_from:
            return date_to
        return last_complete_period_end

    @staticmethod
    def _split_on_day_boundary(date_from: datetime, date_to: datetime) -> tuple[datetime, datetime]:
        """First window's end and second window's start, cut so the two halves never share a day.

        The trends runner snaps each window's bounds to whole days, so a sub-day midpoint would land
        the boundary day in *both* windows and count its events twice. Splitting on a day boundary
        keeps the windows disjoint and contiguous: the boundary day belongs to the second window and
        the first window ends the day before. Clamped so the first window always keeps its opening day.
        """
        midpoint = date_from + (date_to - date_from) / 2
        second_window_start = midpoint.replace(hour=0, minute=0, second=0, microsecond=0)
        earliest_split = date_from.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        second_window_start = max(second_window_start, earliest_split)
        return second_window_start - timedelta(days=1), second_window_start

    def _aggregate_window(self, start: datetime, end: datetime) -> TrendsQueryResponse:
        """Total value of the metric over a single window, reusing the standard trends path."""
        window_query = self.query.model_copy(deep=True)
        window_query.dateRange = DateRange(date_from=start.isoformat(), date_to=end.isoformat())
        # The two halves *are* the comparison — don't also pull in the period before the range.
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
        order = (result.get("action") or {}).get("order", 0)
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
