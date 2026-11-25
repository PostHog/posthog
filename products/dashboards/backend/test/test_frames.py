import datetime as dt
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import (
    BreakdownFilter,
    ChartDisplayType,
    EventsNode,
    MetricsQuery,
    MetricsQueryClause,
    TrendsFilter,
    TrendsQuery,
)

from posthog.caching.insight_result import InsightResult

from products.dashboards.backend.facade.api import insight_frames

NOW = "2026-09-19T12:00:00Z"


def _ms(iso: str) -> int:
    return int(dt.datetime.fromisoformat(iso).timestamp() * 1000)


def _row(label: str, data: list[float], *, days: list[str], **extra: Any) -> dict:
    return {"label": label, "custom_name": None, "order": 0, "days": days, "data": data, **extra}


class TestInsightFramesFromCachedRows(SimpleTestCase):
    @parameterized.expand([("UTC", "2026-09-12T00:00:00+00:00"), ("America/New_York", "2026-09-12T00:00:00-04:00")])
    def test_trends_line_is_one_frame_on_the_project_wall_clock(self, timezone: str, first_day: str) -> None:
        days = [f"2026-09-{day}" for day in range(12, 20)]
        result = InsightResult(
            result=[_row("$pageview", [0, 0, 0, 0, 0, 0, 1, 2], days=days)],
            last_refresh=None,
            cache_key=None,
            is_cached=True,
            timezone=timezone,
            resolved_date_range={"date_from": first_day, "date_to": "2026-09-19T23:59:59.999999" + first_day[-6:]},
        )

        frames = insight_frames(TrendsQuery(series=[EventsNode(event="$pageview")]).model_dump(), result)

        assert frames is not None
        [frame] = frames
        assert frame.fields[0].values == [_ms(first_day) + day * 86_400_000 for day in range(8)]
        assert frame.fields[1].values == [0, 0, 0, 0, 0, 0, 1, 2]
        assert (frame.name, frame.labels, frame.meta.interval) == ("$pageview", {"series_index": "0"}, "day")

    def test_compared_frames_carry_their_own_period(self) -> None:
        days = ["2026-09-18", "2026-09-19"]
        result = InsightResult(
            result=[
                _row("Views", [1, 2], days=days, compare_label="current"),
                _row("Views", [3, 4], days=["2026-09-11", "2026-09-12"], compare_label="previous"),
            ],
            last_refresh=None,
            cache_key=None,
            is_cached=True,
            timezone="UTC",
            resolved_date_range={"date_from": "2026-09-18T00:00:00+00:00", "date_to": "2026-09-19T23:59:59+00:00"},
            resolved_compare_date_range={
                "date_from": "2026-09-11T00:00:00+00:00",
                "date_to": "2026-09-12T23:59:59+00:00",
            },
        )

        frames = insight_frames(TrendsQuery(series=[EventsNode(event="$pageview")]).model_dump(), result)

        assert frames is not None
        current, previous = frames
        assert (current.name, current.meta.previous) == ("Views", False)
        assert (previous.name, previous.meta.previous) == ("Views (previous)", True)
        assert previous.meta.date_from == dt.datetime(2026, 9, 11, tzinfo=dt.UTC)
        current_start = current.fields[0].values[0]
        assert isinstance(current_start, int)
        assert previous.fields[0].values[0] == current_start - 7 * 86_400_000

    def test_trends_shown_as_one_number_per_series_are_not_framed(self) -> None:
        query = TrendsQuery(
            series=[EventsNode(event="$pageview")], trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER)
        )
        result = InsightResult(result=[], last_refresh=None, cache_key=None, is_cached=True, timezone="UTC")

        assert insight_frames(query.model_dump(), result) is None

    def test_breakdown_values_name_and_label_each_frame(self) -> None:
        result = InsightResult(
            result=[
                _row("chrome", [1], days=["2026-09-19"], breakdown_value="chrome"),
                _row(
                    "$$_posthog_breakdown_null_$$",
                    [1],
                    days=["2026-09-19"],
                    breakdown_value="$$_posthog_breakdown_null_$$",
                ),
            ],
            last_refresh=None,
            cache_key=None,
            is_cached=True,
            timezone="UTC",
        )
        query = TrendsQuery(
            series=[EventsNode(event="$pageview")], breakdownFilter=BreakdownFilter(breakdown="$browser")
        )

        frames = insight_frames(query.model_dump(), result)

        assert frames is not None
        assert [(frame.name, frame.labels["breakdown_value"]) for frame in frames] == [
            ("chrome", "chrome"),
            ("None", "$$_posthog_breakdown_null_$$"),
        ]

    def _trends_row(self, label: str, breakdown_value: Any, order: int, custom_name: str | None = None) -> dict:
        return {
            "label": label,
            "custom_name": custom_name,
            "breakdown_value": breakdown_value,
            "order": order,
            "days": ["2026-09-18"],
            "data": [1],
        }

    @parameterized.expand(
        [
            (
                "formula_names_each_breakdown_value",
                TrendsQuery(
                    series=[EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
                    breakdownFilter=BreakdownFilter(breakdown="$browser"),
                    trendsFilter=TrendsFilter(formula="A+B"),
                ),
                [("Formula (A+B)", "chrome", 0, None), ("Formula (A+B)", "$$_posthog_breakdown_null_$$", 0, None)],
                ["Formula (A+B) - chrome", "Formula (A+B) - None"],
            ),
            (
                "renamed_series_keeps_the_cohort_name",
                TrendsQuery(
                    series=[EventsNode(event="$pageview", custom_name="Views"), EventsNode(event="$pageleave")],
                    breakdownFilter=BreakdownFilter(breakdown=[42], breakdown_type="cohort"),
                ),
                [("$pageview - Returning users", 42, 0, "Views"), ("$pageleave - Returning users", 42, 1, None)],
                ["Views - Returning users", "$pageleave - Returning users"],
            ),
        ]
    )
    def test_trends_frame_names(
        self, _name: str, query: TrendsQuery, rows: list[tuple[str, Any, int, str | None]], expected: list[str]
    ) -> None:
        result = InsightResult(
            result=[self._trends_row(*row) for row in rows],
            last_refresh=None,
            cache_key=None,
            is_cached=True,
            timezone="UTC",
        )

        frames = insight_frames(query.model_dump(), result)

        assert frames is not None
        assert [frame.name for frame in frames] == expected

    def test_metrics_interval_is_resolved_on_the_project_wall_clock_across_dst(self) -> None:
        # 60 wall-clock hours, 61 elapsed: the clocks go back on 2026-11-01 in New York.
        result = InsightResult(
            result=[{"labels": {}, "metricName": "queue_depth", "points": []}],
            last_refresh=None,
            cache_key=None,
            is_cached=True,
            timezone="America/New_York",
            resolved_date_range={"date_from": "2026-10-31T00:00:00-04:00", "date_to": "2026-11-02T12:00:00-05:00"},
        )
        query = MetricsQuery(clauses=[MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum")])

        frames = insight_frames(query.model_dump(), result)

        assert frames is not None
        assert frames[0].meta.interval == "hour"
