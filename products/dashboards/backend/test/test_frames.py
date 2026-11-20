import datetime as dt
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import (
    BreakdownFilter,
    ChartDisplayType,
    CompareFilter,
    DateRange,
    EventsNode,
    InsightVizNode,
    MetricsQuery,
    MetricsQueryClause,
    MetricsQueryGroupBy,
    TrendsFilter,
    TrendsQuery,
)

from posthog.caching.insight_result import InsightResult
from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner

from products.dashboards.backend.facade.api import insight_frames
from products.dashboards.backend.facade.contracts import Frame, FrameField, FrameMeta
from products.metrics.backend.facade.testing import seed_metric

NOW = "2026-09-19T12:00:00Z"


def _ms(iso: str) -> int:
    return int(dt.datetime.fromisoformat(iso).timestamp() * 1000)


class TestInsightFrames(ClickhouseTestMixin, APIBaseTest):
    def _frames(self, query: Any) -> list[Frame] | None:
        response = get_query_runner(query, self.team).run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        return insight_frames(query.model_dump(), InsightResult.from_response_dict(response.model_dump()))

    def _seed_pageviews(self) -> None:
        for timestamp, browser in (
            ("2026-09-10T10:00:00Z", "chrome"),
            ("2026-09-18T10:00:00Z", "chrome"),
            ("2026-09-19T10:00:00Z", "safari"),
            ("2026-09-19T11:00:00Z", None),
        ):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="person",
                timestamp=timestamp,
                properties={"$browser": browser} if browser else {},
            )
        flush_persons_and_events()

    @parameterized.expand([("UTC", "2026-09-12T00:00:00+00:00"), ("America/New_York", "2026-09-12T00:00:00-04:00")])
    @time_machine.travel(NOW, tick=False)
    def test_trends_line_is_one_frame_on_the_project_wall_clock(self, timezone: str, first_day: str) -> None:
        self.team.timezone = timezone
        self.team.save()
        self._seed_pageviews()

        frames = self._frames(
            InsightVizNode(
                source=TrendsQuery(series=[EventsNode(event="$pageview")], dateRange=DateRange(date_from="-7d"))
            )
        )

        assert frames is not None
        [frame] = frames
        days = [_ms(first_day) + day * 86_400_000 for day in range(8)]
        assert frame == Frame(
            name="$pageview",
            labels={"series_index": "0"},
            fields=[
                FrameField(name="time", type="time", values=days),
                FrameField(name="value", type="number", values=[0, 0, 0, 0, 0, 0, 1, 2]),
            ],
            meta=FrameMeta(
                interval="day",
                date_from=dt.datetime.fromisoformat(first_day),
                date_to=dt.datetime.fromisoformat(first_day) + dt.timedelta(days=8, microseconds=-1),
            ),
        )

    @parameterized.expand(
        [
            (
                "bar_with_breakdown",
                TrendsQuery(
                    series=[EventsNode(event="$pageview")],
                    dateRange=DateRange(date_from="-7d"),
                    breakdownFilter=BreakdownFilter(breakdown="$browser"),
                    trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_BAR),
                ),
                [
                    ("chrome", {"series_index": "0", "breakdown_value": "chrome"}, False, 1),
                    ("safari", {"series_index": "0", "breakdown_value": "safari"}, False, 1),
                    ("None", {"series_index": "0", "breakdown_value": "$$_posthog_breakdown_null_$$"}, False, 1),
                ],
            ),
            (
                "several_series_with_breakdown",
                TrendsQuery(
                    series=[EventsNode(event="$pageview", custom_name="Views"), EventsNode(event="$pageview")],
                    dateRange=DateRange(date_from="-7d"),
                    breakdownFilter=BreakdownFilter(breakdown="$browser"),
                ),
                [
                    ("Views - chrome", {"series_index": "0", "breakdown_value": "chrome"}, False, 1),
                    ("Views - safari", {"series_index": "0", "breakdown_value": "safari"}, False, 1),
                    (
                        "Views - None",
                        {"series_index": "0", "breakdown_value": "$$_posthog_breakdown_null_$$"},
                        False,
                        1,
                    ),
                    ("$pageview - chrome", {"series_index": "1", "breakdown_value": "chrome"}, False, 1),
                    ("$pageview - safari", {"series_index": "1", "breakdown_value": "safari"}, False, 1),
                    (
                        "$pageview - None",
                        {"series_index": "1", "breakdown_value": "$$_posthog_breakdown_null_$$"},
                        False,
                        1,
                    ),
                ],
            ),
            (
                "compare_to_previous_period",
                TrendsQuery(
                    series=[EventsNode(event="$pageview", custom_name="Views")],
                    dateRange=DateRange(date_from="-7d"),
                    compareFilter=CompareFilter(compare=True),
                ),
                [
                    ("Views", {"series_index": "0"}, False, 3),
                    ("Views (previous)", {"series_index": "0"}, True, 1),
                ],
            ),
        ]
    )
    @time_machine.travel(NOW, tick=False)
    def test_trends_series_become_one_frame_each(
        self, _name: str, query: TrendsQuery, expected: list[tuple[str, dict[str, str], bool, int]]
    ) -> None:
        self._seed_pageviews()

        frames = self._frames(query)

        assert frames is not None
        assert [
            (frame.name, frame.labels, frame.meta.previous, sum(value or 0 for value in frame.fields[1].values))
            for frame in frames
        ] == expected
        assert all(len(frame.fields[0].values) == len(frame.fields[1].values) == 8 for frame in frames)

    @time_machine.travel(NOW, tick=False)
    def test_compared_frames_carry_their_own_period(self) -> None:
        self._seed_pageviews()

        frames = self._frames(
            TrendsQuery(
                series=[EventsNode(event="$pageview")],
                dateRange=DateRange(date_from="-7d"),
                compareFilter=CompareFilter(compare=True),
            )
        )

        assert frames is not None
        current, previous = frames
        assert current.meta.date_from is not None
        assert previous.meta.date_from == current.meta.date_from - dt.timedelta(days=7)
        assert previous.fields[0].values[0] == (current.fields[0].values[0] or 0) - 7 * 86_400_000

    @time_machine.travel(NOW, tick=False)
    def test_trends_shown_as_one_number_per_series_are_not_framed(self) -> None:
        self._seed_pageviews()

        frames = self._frames(
            TrendsQuery(
                series=[EventsNode(event="$pageview")],
                trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
            )
        )

        assert frames is None

    @time_machine.travel(NOW, tick=False)
    def test_metrics_series_become_one_frame_each(self) -> None:
        base = dt.datetime(2026, 9, 19, 11, 30, tzinfo=dt.UTC)
        for container, value in (("capture", 5.0), ("ingestion", 7.0)):
            seed_metric(
                team_id=self.team.pk,
                metric_name="queue_depth",
                metric_type="gauge",
                unit="By",
                points=[(base + dt.timedelta(minutes=minute), value) for minute in (0, 1, 3)],
                labels={"container": container},
            )

        frames = self._frames(
            MetricsQuery(
                clauses=[
                    MetricsQueryClause(
                        name="a",
                        metricName="queue_depth",
                        aggregation="sum",
                        groupBy=[MetricsQueryGroupBy(key="container")],
                    )
                ],
                dateRange=DateRange(date_from="2026-09-19T11:00:00Z", date_to="2026-09-19T12:00:00Z"),
            )
        )

        assert frames is not None
        times = [_ms(f"2026-09-19T11:3{minute}:00+00:00") for minute in (0, 1, 3)]
        meta = FrameMeta(
            interval="minute",
            date_from=dt.datetime(2026, 9, 19, 11, tzinfo=dt.UTC),
            date_to=dt.datetime(2026, 9, 19, 12, tzinfo=dt.UTC),
        )
        assert sorted(frames, key=lambda frame: frame.name) == [
            Frame(
                name=f"container={container}",
                labels={"container": container},
                fields=[
                    FrameField(name="time", type="time", values=times),
                    FrameField(name="value", type="number", values=[value] * 3, unit="By"),
                ],
                meta=meta,
            )
            for container, value in (("capture", 5.0), ("ingestion", 7.0))
        ]


class TestInsightFramesFromCachedRows(SimpleTestCase):
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
