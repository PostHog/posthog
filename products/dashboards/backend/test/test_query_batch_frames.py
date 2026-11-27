import json
import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import BreakdownFilter, EventsNode, EventsQuery, HogQLQuery, IntervalType, TrendsFilter, TrendsQuery

from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner

from products.dashboards.backend.facade.contracts import Frame, FrameField, FrameMeta
from products.dashboards.backend.facade.enums import QueryBatchLanguage, QueryBatchTargetFormat
from products.dashboards.backend.v2.frames import (
    MAX_LEGEND_NAME,
    MAX_PIVOT_LABEL_BYTES,
    MAX_PIVOT_SERIES,
    MAX_PROMETHEUS_SERIES,
    MAX_RECORD_FIELDS,
    MAX_STREAM_LABEL_BYTES,
    frame_json,
    frames_for,
    legend_name,
    pivot_long,
)

NOW = "2026-09-19T12:00:00Z"


def _ms(iso: str) -> int:
    return int(dt.datetime.fromisoformat(iso).timestamp() * 1000)


_FUNNEL_STEPS = [{"kind": "EventsNode", "event": "$pageview"}, {"kind": "EventsNode", "event": "signup"}]
_RUNNER_RESPONSES = json.loads((Path(__file__).parent / "runner_responses.json").read_text())
_LIFECYCLE_DAYS = [_ms(f"2026-09-{day}T00:00:00+00:00") for day in range(12, 20)]


def _shape(frames: list[dict[str, Any]] | None) -> list[tuple[Any, dict, list]]:
    assert frames is not None
    return [(frame["name"], frame["labels"], [field["values"] for field in frame["fields"]]) for frame in frames]


class TestFramesFromRealRunners(ClickhouseTestMixin, APIBaseTest):
    def _run(self, query: Any) -> dict[str, Any]:
        response = get_query_runner(query, self.team).run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        return response.model_dump(by_alias=True)

    def _seed(self) -> None:
        for day, browser, count in (
            ("2026-09-17", "Chrome", 2),
            ("2026-09-18", "Chrome", 1),
            ("2026-09-18", "Safari", 3),
        ):
            for _ in range(count):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id="user",
                    timestamp=f"{day}T10:00:00Z",
                    properties={"$browser": browser},
                )
        flush_persons_and_events()

    @time_machine.travel(NOW, tick=False)
    def test_hogql_long_table_pivots_to_one_frame_per_label(self) -> None:
        self._seed()
        query = HogQLQuery(
            query=(
                "SELECT toStartOfDay(timestamp) AS day, properties.$browser AS browser, count() AS views "
                "FROM events GROUP BY day, browser ORDER BY day, browser"
            )
        )
        result = self._run(query)

        frames = frames_for(QueryBatchLanguage.HOGQL, query.model_dump(), result)
        table = frames_for(
            QueryBatchLanguage.HOGQL, query.model_dump(), result, target_format=QueryBatchTargetFormat.TABLE
        )

        day_17, day_18 = _ms("2026-09-17T00:00:00+00:00"), _ms("2026-09-18T00:00:00+00:00")
        assert _shape(frames) == [
            ("Chrome", {"browser": "Chrome"}, [[day_17, day_18], [2, 1]]),
            ("Safari", {"browser": "Safari"}, [[day_18], [3]]),
        ]
        assert frames is not None
        assert [field["type"] for field in frames[0]["fields"]] == ["time", "number"]
        assert frames[0]["fields"][1]["labels"] == {"browser": "Chrome"}
        assert _shape(table) == [
            (None, {}, [[day_17, day_18, day_18], ["Chrome", "Chrome", "Safari"], [2, 1, 3]]),
        ]

    @time_machine.travel(NOW, tick=False)
    def test_hogql_without_a_time_column_is_one_table_frame(self) -> None:
        self._seed()
        query = HogQLQuery(
            query="SELECT properties.$browser AS browser, count() AS views FROM events GROUP BY browser ORDER BY browser"
        )

        frames = frames_for(QueryBatchLanguage.HOGQL, query.model_dump(), self._run(query))

        assert _shape(frames) == [(None, {}, [["Chrome", "Safari"], [3, 3]])]
        assert frames is not None
        assert [field["type"] for field in frames[0]["fields"]] == ["string", "number"]
        assert frames[0]["meta"]["end"] is None

    @time_machine.travel(NOW, tick=False)
    def test_an_events_table_is_not_pivoted_into_series(self) -> None:
        self._seed()
        query = EventsQuery(
            select=["toStartOfDay(timestamp)", "properties.$browser", "count()"],
            orderBy=["toStartOfDay(timestamp)", "properties.$browser"],
            event="$pageview",
            after="-7d",
        )

        frames = frames_for(QueryBatchLanguage.QUERY, query.model_dump(), self._run(query))

        day_17, day_18 = _ms("2026-09-17T00:00:00+00:00"), _ms("2026-09-18T00:00:00+00:00")
        assert _shape(frames) == [(None, {}, [[day_17, day_18, day_18], ["Chrome", "Chrome", "Safari"], [2, 1, 3]])]


class TestFrameConverters(SimpleTestCase):
    # Rows in the shape TrendsQueryRunner returns, as in PR #138426's frames tests. A dashboards test may not run
    # another product's runner.
    @parameterized.expand([("UTC", "2026-09-12T00:00:00+00:00"), ("America/New_York", "2026-09-12T00:00:00-04:00")])
    def test_trends_line_is_one_frame_on_the_project_wall_clock(self, timezone: str, first_day: str) -> None:
        days = [f"2026-09-{day}" for day in range(12, 20)]
        result = {
            "results": [{"label": "$pageview", "order": 0, "days": days, "data": [0, 0, 0, 0, 0, 0, 1, 2]}],
            "timezone": timezone,
            "resolved_date_range": {"date_from": first_day, "date_to": "2026-09-19T23:59:59" + first_day[-6:]},
        }
        query = TrendsQuery(series=[EventsNode(event="$pageview")])

        frames = frames_for(QueryBatchLanguage.QUERY, query.model_dump(), result)

        times = [_ms(first_day) + day * 86_400_000 for day in range(8)]
        assert _shape(frames) == [("$pageview", {"series_index": "0"}, [times, [0, 0, 0, 0, 0, 0, 1, 2]])]
        assert frames is not None
        assert (frames[0]["meta"]["interval"], frames[0]["meta"]["end"]) == ("day", times[-1])

    @parameterized.expand(
        [
            (
                "breakdown_values",
                TrendsQuery(
                    series=[EventsNode(event="$pageview")], breakdownFilter=BreakdownFilter(breakdown="$browser")
                ),
                [("chrome", "chrome", None), ("$$_posthog_breakdown_null_$$", "$$_posthog_breakdown_null_$$", None)],
                ["chrome", "None"],
            ),
            (
                "formula_names_each_breakdown_value",
                TrendsQuery(
                    series=[EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
                    breakdownFilter=BreakdownFilter(breakdown="$browser"),
                    trendsFilter=TrendsFilter(formula="A+B"),
                ),
                [("Formula (A+B)", "chrome", None), ("Formula (A+B)", "$$_posthog_breakdown_null_$$", None)],
                ["Formula (A+B) - chrome", "Formula (A+B) - None"],
            ),
        ]
    )
    def test_trends_frame_names(
        self, _name: str, query: TrendsQuery, rows: list[tuple[str, Any, str | None]], expected: list[str]
    ) -> None:
        result = {
            "results": [
                {
                    "label": label,
                    "breakdown_value": value,
                    "custom_name": custom,
                    "order": 0,
                    "days": ["2026-09-18"],
                    "data": [1],
                }
                for label, value, custom in rows
            ],
            "timezone": "UTC",
        }

        frames = frames_for(QueryBatchLanguage.QUERY, query.model_dump(), result)

        assert frames is not None
        assert [frame["name"] for frame in frames] == expected

    def test_legend_names_trends_frames_by_breakdown(self) -> None:
        query = TrendsQuery(
            series=[EventsNode(event="$pageview")], breakdownFilter=BreakdownFilter(breakdown="$browser")
        )
        result = {"results": [{"label": "chrome", "breakdown_value": "chrome", "order": 0, "days": [], "data": []}]}

        frames = frames_for(QueryBatchLanguage.QUERY, query.model_dump(), result, legend="Browser {{breakdown_value}}")

        assert frames is not None
        assert frames[0]["name"] == "Browser chrome"

    def test_pivot_keeps_every_label_column(self) -> None:
        frame = Frame(
            name=None,
            labels={},
            fields=[
                FrameField(name="t", type="time", values=[1, 1, 2, 2, 2]),
                FrameField(name="client", type="string", values=["codex", "claude", "codex", None, "(none)"]),
                FrameField(name="region", type="string", values=["us", "eu", "us", "us", "us"]),
                FrameField(name="n", type="number", values=[5, 3, 6, 4, 7]),
            ],
            meta=FrameMeta(),
        )

        frames = pivot_long(frame)

        assert [(f.name, f.labels, f.fields[1].values) for f in frames] == [
            ("codex / us", {"client": "codex", "region": "us"}, [5, 6]),
            ("claude / eu", {"client": "claude", "region": "eu"}, [3]),
            ("(none) / us", {"client": "(none)", "region": "us"}, [4]),
            ("(none) / us", {"client": "(none)", "region": "us"}, [7]),
        ]

    def test_pivot_counts_the_column_names_every_series_repeats(self) -> None:
        clients = [f"client-{n}" for n in range(MAX_PIVOT_SERIES - 1)]
        frame = Frame(
            name=None,
            labels={},
            fields=[
                FrameField(name="t", type="time", values=[1] * len(clients)),
                FrameField(name="client", type="string", values=clients),
                FrameField(name="n" * 10_000, type="number", values=[1] * len(clients)),
            ],
            meta=FrameMeta(),
        )

        assert pivot_long(frame) == [frame]

    def test_trends_hours_repeated_by_the_autumn_clock_change_stay_an_hour_apart(self) -> None:
        days = ["2026-11-01 00:00:00", "2026-11-01 01:00:00", "2026-11-01 01:00:00", "2026-11-01 02:00:00"]
        result = {
            "results": [{"label": "$pageview", "order": 0, "days": days, "data": [1, 2, 3, 4]}],
            "timezone": "America/New_York",
        }
        query = TrendsQuery(series=[EventsNode(event="$pageview")], interval=IntervalType.HOUR)

        frames = frames_for(QueryBatchLanguage.QUERY, query.model_dump(), result)

        assert frames is not None
        times = frames[0]["fields"][0]["values"]
        assert [later - earlier for earlier, later in zip(times, times[1:])] == [3_600_000] * 3

    @parameterized.expand(
        [
            ("too_many_series", [f"client-{n}" for n in range(MAX_PIVOT_SERIES + 1)], 1),
            ("labels_too_large", ["x" * (MAX_PIVOT_LABEL_BYTES // 2)], 2),
            ("too_many_fields", [f"client-{n}" for n in range(500)], 40),
        ]
    )
    def test_pivot_keeps_a_table_that_would_grow_too_large(
        self, _name: str, clients: list[str], number_columns: int
    ) -> None:
        frame = Frame(
            name=None,
            labels={},
            fields=[
                FrameField(name="t", type="time", values=[1] * len(clients)),
                FrameField(name="client", type="string", values=clients),
                *(FrameField(name=f"n{i}", type="number", values=[1] * len(clients)) for i in range(number_columns)),
            ],
            meta=FrameMeta(),
        )

        assert pivot_long(frame) == [frame]

    @parameterized.expand(
        [
            ("dotted_labels", "{{k8s.pod.name}} p{{ p }}", {"k8s.pod.name": "web-1", "p": "99"}, "web-1 p99"),
            ("missing_label_is_empty", "{{job}}-{{nope}}", {"job": "api"}, "api-"),
            (
                "label_names_with_dashes_and_spaces",
                "{{client-name}} / {{ browser name }}",
                {"client-name": "codex", "browser name": "Chrome"},
                "codex / Chrome",
            ),
            ("long_names_are_cut", "{{x}}" * 200, {"x": "y" * 10_000}, "y" * MAX_LEGEND_NAME),
            ("unclosed_label_of_spaces", "{{" + " " * 5000 + "x", {}, ("{{" + " " * 5000 + "x")[:MAX_LEGEND_NAME]),
        ]
    )
    def test_legend_template(self, _name: str, template: str, labels: dict[str, str], expected: str) -> None:
        assert legend_name(template, labels) == expected

    def test_legend_names_prometheus_frames_from_their_labels(self) -> None:
        result = {
            "results": {
                "resultType": "matrix",
                "result": [
                    {"metric": {"__name__": "up", "job": "api", "code": "200"}, "values": [[10, "1"], [20, "NaN"]]},
                    {"metric": {"job": "web", "code": "500"}, "values": [[10, "2"]]},
                ],
            }
        }

        frames = frames_for(QueryBatchLanguage.LOGQL, {}, result, legend="{{job}} ({{code}})")

        assert _shape(frames) == [
            ("api (200)", {"job": "api", "code": "200"}, [[10_000, 20_000], [1.0, None]]),
            ("web (500)", {"job": "web", "code": "500"}, [[10_000], [2.0]]),
        ]

    def test_prometheus_vector_and_default_names(self) -> None:
        result = {"results": {"resultType": "vector", "result": [{"metric": {"job": "api"}, "value": [30, "4"]}]}}

        assert _shape(frames_for(QueryBatchLanguage.LOGQL, {}, result)) == [("api", {"job": "api"}, [[30_000], [4.0]])]

    def test_log_streams_in_the_same_millisecond_stay_newest_first(self) -> None:
        result = {
            "results": {
                "resultType": "streams",
                "result": [
                    {"stream": {"service": "api"}, "values": [["1000000100", "older"]]},
                    {"stream": {"service": "web"}, "values": [["1000000900", "newer"]]},
                ],
            }
        }

        frames = frames_for(QueryBatchLanguage.LOGQL, {}, result)

        assert frames is not None
        assert frames[0]["fields"][1]["values"] == ["newer", "older"]
        assert frames[0]["fields"][0]["values"] == [1000, 1000]

    def test_log_streams_are_one_table_newest_first(self) -> None:
        result = {
            "results": {
                "resultType": "streams",
                "result": [
                    {"stream": {"service": "api"}, "values": [["1000000000", "first"], ["3000000000", "third"]]},
                    {"stream": {"service": "web"}, "values": [["2000000000", "second"]]},
                ],
            }
        }

        assert _shape(frames_for(QueryBatchLanguage.LOGQL, {}, result)) == [
            (
                None,
                {},
                [[3000, 2000, 1000], ["third", "second", "first"], ["service=api", "service=web", "service=api"]],
            )
        ]

    @parameterized.expand(
        [
            ("ascii", "y" * (MAX_STREAM_LABEL_BYTES // 2), 2),
            ("four_byte_characters", "😀" * (MAX_STREAM_LABEL_BYTES // 8), 3),
        ]
    )
    def test_log_streams_with_too_many_repeated_label_bytes_stay_raw(self, _name: str, label: str, lines: int) -> None:
        values = [[str(n), "line"] for n in range(lines)]
        result = {"results": {"resultType": "streams", "result": [{"stream": {"x": label}, "values": values}]}}

        assert frames_for(QueryBatchLanguage.LOGQL, {}, result) is None

    @parameterized.expand([("matrix", "values", [[10, "1"]]), ("vector", "value", [10, "1"])])
    def test_prometheus_results_with_too_many_series_stay_raw(self, result_type: str, key: str, value: Any) -> None:
        series = [{"metric": {"pod": f"web-{n}"}, key: value} for n in range(MAX_PROMETHEUS_SERIES + 1)]
        result = {"results": {"resultType": result_type, "result": series}}

        assert frames_for(QueryBatchLanguage.LOGQL, {}, result) is None
        assert frames_for(QueryBatchLanguage.LOGQL, {}, {"results": {**result["results"], "result": series[:-1]}})

    def test_metrics_frames_give_no_interval_the_runner_may_have_coarsened(self) -> None:
        result = {"results": [{"labels": {}, "metricName": "up", "points": [{"time": NOW, "value": 1}]}]}

        frames = frames_for(QueryBatchLanguage.QUERY, {"kind": "MetricsQuery", "interval": "minute"}, result)

        assert frames is not None
        assert frames[0]["meta"]["interval"] is None

    @parameterized.expand(
        [
            ("cached", list, ["href", "https://example.com/x"], "https://example.com/x"),
            ("fresh", tuple, ["href", "https://example.com/x"], "https://example.com/x"),
            ("attribute_values_that_read_as_keys", list, ["title", "href", "href", "children"], "children"),
        ]
    )
    def test_hogql_html_tags_become_text_and_a_link_column(
        self, _name: str, sequence: type, attributes: list[str], href: str
    ) -> None:
        link = sequence(["__hx_tag", "a", *attributes, "children", sequence(["f", "Jul ", "2026"])])
        result = {
            "columns": ["month", "n"],
            "types": [["month", "String"], ["n", "UInt64"]],
            "results": [[link, 1]],
        }

        frames = frames_for(QueryBatchLanguage.HOGQL, {"kind": "HogQLQuery"}, result)

        assert _shape(frames) == [(None, {}, [["Jul 2026"], [href], [1]])]

    def test_hogql_column_types_follow_the_scalar_type(self) -> None:
        result = {
            "columns": ["t", "ids", "browser", "status", "n"],
            "types": [
                ["t", "DateTime"],
                ["ids", "Array(UInt64)"],
                ["browser", "String"],
                ["status", "Enum8('ok' = 1, 'timeout' = 2, 'print' = 3)"],
                ["n", "UInt64"],
            ],
            "results": [["2026-09-18T00:00:00", [1, 2], "Chrome", "timeout", 3]],
        }

        frames = frames_for(QueryBatchLanguage.HOGQL, {"kind": "HogQLQuery"}, result)

        assert frames is not None
        assert [[field["type"] for field in frame["fields"]] for frame in frames] == [
            ["time", "other", "string", "string", "number"]
        ]

    @parameterized.expand(
        [
            (
                "trends_number_with_compare",
                [
                    ("$pageview", {"series_index": "0"}, [[5]]),
                    ("$pageview (previous)", {"series_index": "0"}, [[0]]),
                ],
            ),
            (
                "trends_pie_by_breakdown",
                [
                    ("Safari", {"series_index": "0", "breakdown_value": "Safari"}, [[3]]),
                    ("Chrome", {"series_index": "0", "breakdown_value": "Chrome"}, [[2]]),
                ],
            ),
            (
                "funnel_steps",
                [
                    (
                        None,
                        {},
                        [["$pageview", "signup"], [2, 1], [100.0, 50.0], [100.0, 50.0], [None, 3600.0], [None, 3600.0]],
                    )
                ],
            ),
            ("funnel_time_to_convert", [("time to convert", {}, [[3600, 3660], [1, 0]])]),
            (
                "retention_cohorts_by_period",
                [
                    (
                        None,
                        {},
                        [
                            [_ms(f"2026-09-{day}T00:00:00+00:00") for day in (16, 17, 18, 19)],
                            [0, 2, 2, 0],
                            [0, 2, 0, 0],
                            [0, 0, 0, 0],
                        ],
                    )
                ],
            ),
            (
                "stickiness_counts_by_interval",
                [("$pageview", {"series_index": "0"}, [[1, 2, 3, 4, 5, 6, 7, 8], [0, 2, 0, 0, 0, 0, 0, 0]])],
            ),
            (
                "lifecycle_status_series",
                [
                    (f"$pageview - {status}", {"series_index": "0", "status": status}, [_LIFECYCLE_DAYS, data])
                    for status, data in (
                        ("new", [0.0] * 8),
                        ("returning", [0.0] * 6 + [2.0, 0.0]),
                        ("resurrecting", [0.0] * 5 + [2.0, 0.0, 0.0]),
                        ("dormant", [0.0] * 7 + [-2.0]),
                    )
                ],
            ),
        ]
    )
    def test_insight_kinds_become_frames(self, name: str, expected: list) -> None:
        # Responses recorded from the real runners over two people's pageviews and one signup, since a dashboards test
        # may not run another product's runner.
        case = _RUNNER_RESPONSES[name]

        frames = frames_for(QueryBatchLanguage.QUERY, case["query"], case["response"])

        assert _shape(frames) == expected

    def test_compared_funnel_steps_get_one_frame_per_period(self) -> None:
        steps = [
            {"name": name, "count": count, "compare_label": label}
            for label, counts in (("current", (4, 2)), ("previous", (10, 1)))
            for name, count in zip(("$pageview", "signup"), counts)
        ]

        frames = frames_for(QueryBatchLanguage.QUERY, {"kind": "FunnelsQuery"}, {"results": steps})

        assert frames is not None
        assert [(frame["name"], frame["meta"].get("previous", False)) for frame in frames] == [
            (None, False),
            ("previous", True),
        ]
        assert [frame["fields"][2]["values"] for frame in frames] == [[100.0, 50.0], [100.0, 10.0]]

    def test_funnel_step_conversion_skips_optional_steps(self) -> None:
        series = [{"kind": "EventsNode", "event": name, "optionalInFunnel": name == "b"} for name in ("a", "b", "c")]
        steps = [{"name": name, "count": count} for name, count in (("a", 8), ("b", 3), ("c", 7))]

        frames = frames_for(QueryBatchLanguage.QUERY, {"kind": "FunnelsQuery", "series": series}, {"results": steps})

        assert frames is not None
        assert frames[0]["fields"][3]["values"] == [100.0, 37.5, 87.5]

    def test_lifecycle_buckets_use_the_project_timezone(self) -> None:
        result = {"results": [{"label": "new", "status": "new", "days": ["2026-09-18"], "data": [1]}]}

        frames = frames_for(QueryBatchLanguage.QUERY, {"kind": "LifecycleQuery"}, result, timezone="America/New_York")

        assert frames is not None
        assert frames[0]["fields"][0]["values"] == [_ms("2026-09-18T00:00:00-04:00")]

    def test_compared_time_to_convert_keeps_both_histograms(self) -> None:
        results = [
            {"bins": [[60, 3], [120, 1]], "compare_label": "current"},
            {"bins": [[60, 2], [120, 0]], "compare_label": "previous"},
        ]

        frames = frames_for(QueryBatchLanguage.QUERY, {"kind": "FunnelsQuery"}, {"results": results})

        assert _shape(frames) == [
            ("time to convert", {}, [[60, 120], [3, 1]]),
            ("time to convert (previous)", {}, [[60, 120], [2, 0]]),
        ]

    @parameterized.expand([("Metric",), ("CalendarHeatmap",), ("BoxPlot",), ("SlopeGraph",)])
    def test_trends_displays_without_an_aggregate_keep_the_raw_result(self, display: str) -> None:
        query = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "$pageview"}],
            "trendsFilter": {"display": display},
        }
        result = {"results": [{"label": "$pageview", "data": [1, 2], "days": ["2026-09-18", "2026-09-19"]}]}

        assert frames_for(QueryBatchLanguage.QUERY, query, result) is None

    def test_retention_keeps_the_aggregated_property_and_raw_breakdowns_apart(self) -> None:
        def cohort(breakdown: str, value: float) -> dict[str, Any]:
            return {
                "date": "2026-09-18T00:00:00Z",
                "breakdown_value": breakdown,
                "values": [{"count": 1, "aggregation_value": value, "label": "Day 0"}],
            }

        rows = [cohort("Other", 7.5), cohort("$$_posthog_breakdown_other_$$", 2.0)]

        frames = frames_for(QueryBatchLanguage.QUERY, {"kind": "RetentionQuery"}, {"results": rows})

        assert [frame["fields"][1]["values"] for frame in (frames or [])] == [[7.5], [2.0]]

    @parameterized.expand(
        [
            ("records_become_a_table", {"results": [{"source": "1_/a", "value": 3}]}, [(None, {}, [["1_/a"], [3]])]),
            ("no_rows_is_no_frames", {"results": []}, []),
            ("rows_that_are_not_records", {"results": [1, 2]}, None),
            ("no_rows_at_all", {"results": {"nodes": []}}, None),
        ]
    )
    def test_a_kind_without_its_own_converter_is_a_table_or_none(
        self, _name: str, result: dict[str, Any], expected: list | None
    ) -> None:
        frames = frames_for(QueryBatchLanguage.QUERY, {"kind": "PathsQuery"}, result)

        assert (frames if expected is None else _shape(frames)) == expected

    @parameterized.expand(
        [
            *((name, None) for name in _RUNNER_RESPONSES),
            *(
                (f"trends_{display}", display)
                for display in ("ActionsTable", "ActionsBarValue", "WorldMap", "BoldNumber")
            ),
        ]
    )
    def test_every_recorded_kind_has_frames(self, name: str, display: str | None) -> None:
        case = _RUNNER_RESPONSES[name] if display is None else _RUNNER_RESPONSES["trends_pie_by_breakdown"]
        query = case["query"] if display is None else {**case["query"], "trendsFilter": {"display": display}}

        for wrapped in (query, {"kind": "InsightVizNode", "source": query}):
            assert frames_for(QueryBatchLanguage.QUERY, wrapped, case["response"]) is not None

    def test_web_table_splits_compared_pairs_into_two_number_columns(self) -> None:
        case = _RUNNER_RESPONSES["web_stats_by_page"]

        [frame] = frames_for(QueryBatchLanguage.QUERY, case["query"], case["response"]) or []

        assert [(field["name"], field["type"], field["values"]) for field in frame["fields"]][:5] == [
            ("breakdown_value", "string", ["/x"]),
            ("visitors", "number", [1]),
            ("visitors (previous)", "number", [None]),
            ("views", "number", [4]),
            ("views (previous)", "number", [None]),
        ]

    @parameterized.expand(
        [
            ("all_null_metric", ["context.columns.visitors"], [[None]], [("visitors", "string", [None])]),
            (
                "viewport_breakdown",
                ["context.columns.breakdown_value", "context.columns.visitors"],
                [[[1920, 1080], [3, 1]]],
                [
                    ("breakdown_value", "other", [[1920, 1080]]),
                    ("visitors", "number", [3]),
                    ("visitors (previous)", "number", [1]),
                ],
            ),
        ]
    )
    def test_web_table_splits_only_metric_columns_holding_a_pair(
        self, _name: str, columns: list[str], rows: list[list[Any]], expected: list[tuple[str, str, list[Any]]]
    ) -> None:
        query = {"kind": "WebStatsTableQuery", "breakdownBy": "Viewport", "properties": []}

        [frame] = frames_for(QueryBatchLanguage.QUERY, query, {"columns": columns, "results": rows}) or []

        assert [(field["name"], field["type"], field["values"]) for field in frame["fields"]] == expected

    def test_sparse_records_past_the_cell_budget_have_no_frames(self) -> None:
        rows = [{f"key_{index}": 1} for index in range(MAX_RECORD_FIELDS + 1)]

        assert frames_for(QueryBatchLanguage.QUERY, {"kind": "HogQuery"}, {"results": rows}) is None

    def test_hash_changes_with_content_and_end_is_the_last_time(self) -> None:
        def frame(values: list[Any]) -> Frame:
            return Frame(
                name="a",
                labels={},
                fields=[
                    FrameField(name="time", type="time", values=[1000, 2000]),
                    FrameField(name="value", type="number", values=values),
                ],
                meta=FrameMeta(),
            )

        first, same, changed = frame_json(frame([1, 2])), frame_json(frame([1, 2])), frame_json(frame([1, 3]))

        assert first["hash"] == same["hash"] != changed["hash"]
        assert frame_json(frame([Decimal("1.5"), 2]))["hash"] == frame_json(frame([1.5, 2]))["hash"]
        assert first["meta"]["end"] == 2000

    def _span_aggregate(self, name: str, count: int, errors: int, p95_ms: float) -> dict[str, Any]:
        nanos = p95_ms * 1_000_000
        return {
            "service_name": "web",
            "name": name,
            "count": count,
            "error_count": errors,
            "avg_duration_nano": nanos / 2,
            "p50_duration_nano": nanos / 2,
            "p95_duration_nano": nanos,
            "p99_duration_nano": nanos,
            "p999_duration_nano": nanos,
            "total_duration_nano": nanos * count,
        }

    def test_span_aggregation_is_one_bar_per_operation_in_milliseconds(self) -> None:
        result = {
            "results": [self._span_aggregate("GET /a", 40, 4, 250.0), self._span_aggregate("GET /b", 10, 0, 80.0)],
            "resolved_date_range": {"date_from": "2026-09-18T12:00:00+00:00", "date_to": NOW},
        }
        query = {"kind": "TraceSpansAggregationQuery", "dateRange": {"date_from": "-24h"}}

        frames = frames_for(QueryBatchLanguage.QUERY, query, result)

        assert frames is not None
        assert [(frame["name"], frame["labels"]) for frame in frames] == [
            ("web / GET /a", {"service": "web", "operation": "GET /a"}),
            ("web / GET /b", {"service": "web", "operation": "GET /b"}),
        ]
        # Bar charts draw a frame's first number field, so traffic leads; impact numbers the query skipped are absent.
        assert [(field["name"], field["values"], field.get("unit")) for field in frames[0]["fields"]] == [
            ("time", [_ms(NOW)], None),
            ("count", [40], None),
            ("error_count", [4], None),
            ("error_rate", [10.0], "%"),
            ("avg_duration", [125.0], "ms"),
            ("p50_duration", [125.0], "ms"),
            ("p95_duration", [250.0], "ms"),
            ("p99_duration", [250.0], "ms"),
        ]

    def test_span_aggregation_as_a_table_is_one_row_per_operation(self) -> None:
        result = {"results": [self._span_aggregate("GET /a", 40, 4, 250.0), self._span_aggregate("GET /b", 0, 0, 0.0)]}
        query = {"kind": "TraceSpansAggregationQuery", "dateRange": {"date_from": "-24h"}}

        frames = frames_for(QueryBatchLanguage.QUERY, query, result, target_format=QueryBatchTargetFormat.TABLE)

        assert _shape(frames)[0][2][:4] == [["web", "web"], ["GET /a", "GET /b"], [40, 0], [4, 0]]
        assert frames is not None
        error_rate = next(field for field in frames[0]["fields"] if field["name"] == "error_rate")
        assert error_rate["values"] == [10.0, None]

    @parameterized.expand(
        [
            ("too_many_operations", [f"GET /{n}" for n in range(MAX_PIVOT_SERIES + 1)]),
            ("names_too_long", ["x" * (MAX_PIVOT_LABEL_BYTES // 4)]),
        ]
    )
    def test_span_aggregation_stays_a_table_when_bars_would_grow_too_large(self, _name: str, names: list[str]) -> None:
        result = {
            "results": [self._span_aggregate(name, 1, 0, 1.0) for name in names],
            "resolved_date_range": {"date_from": "2026-09-18T12:00:00+00:00", "date_to": NOW},
        }
        query = {"kind": "TraceSpansAggregationQuery", "dateRange": {"date_from": "-24h"}}

        frames = frames_for(QueryBatchLanguage.QUERY, query, result)

        assert frames is not None
        assert len(frames) == 1
        assert frames[0]["fields"][1]["values"] == names

    def test_span_list_is_one_table_frame(self) -> None:
        span = {
            "uuid": "u1",
            "trace_id": "t1",
            "span_id": "s1",
            "parent_span_id": "",
            "name": "GET /a",
            "kind": 2,
            "service_name": "web",
            "status_code": 0,
            "timestamp": dt.datetime(2026, 9, 19, 12, tzinfo=dt.UTC),
            "end_time": dt.datetime(2026, 9, 19, 12, tzinfo=dt.UTC),
            "duration_nano": 3_500_000,
            "is_root_span": True,
        }

        frames = frames_for(QueryBatchLanguage.QUERY, {"kind": "TraceSpansQuery"}, {"results": [span], "hasMore": True})

        assert frames is not None
        [frame] = frames
        assert [(field["name"], field["values"]) for field in frame["fields"]] == [
            ("time", [_ms(NOW)]),
            ("service", ["web"]),
            ("operation", ["GET /a"]),
            ("duration", [3.5]),
            ("status_code", [0]),
            ("kind", [2]),
            ("is_root_span", [True]),
            ("trace_id", ["t1"]),
            ("span_id", ["s1"]),
        ]
        assert frame["meta"]["truncated"] is True
