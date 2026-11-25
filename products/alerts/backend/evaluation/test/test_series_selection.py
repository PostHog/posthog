from unittest import TestCase

from parameterized import parameterized

from posthog.schema import ChartDisplayType, CompareFilter, EventsNode, TrendsFilter, TrendsQuery

from posthog.caching.insight_result import InsightResult
from posthog.tasks.alerts.trends import _pick_series_result

from products.alerts.backend.evaluation.contract import AlertDataUnavailableError, AlertExtractionError


def _rows(count: int) -> InsightResult:
    return InsightResult(
        result=[{"label": f"row {i}", "data": [1.0]} for i in range(count)],
        last_refresh=None,
        cache_key="",
        is_cached=False,
        timezone="UTC",
    )


def _query(series: int, **trends_filter) -> TrendsQuery:
    return TrendsQuery(
        series=[EventsNode(event=f"event {i}") for i in range(series)], trendsFilter=TrendsFilter(**trends_filter)
    )


class TestPickSeriesResult(TestCase):
    @parameterized.expand(
        [
            ("formula added after the alert", _query(2, formula="A+B"), 1, 1),
            ("legacy formulas list", _query(4, formulas=["A+B+C", "D"]), 2, 3),
            ("series removed after the alert", _query(3), 3, 3),
            ("calendar heatmap reports one row", _query(2, display=ChartDisplayType.CALENDAR_HEATMAP), 1, 1),
            ("negative index", _query(2), 2, -1),
            (
                "compare mode puts previous-period rows past the defined count",
                _query(2).model_copy(update={"compareFilter": CompareFilter(compare=True)}),
                4,
                3,
            ),
        ]
    )
    def test_an_index_past_what_the_insight_defines_is_a_broken_config(self, _name, query, rows, series_index):
        with self.assertRaisesRegex(AlertExtractionError, "the insight no longer has"):
            _pick_series_result(series_index, _rows(rows), query)

    def test_a_short_result_within_what_the_insight_defines_keeps_the_alert_enabled(self):
        with self.assertRaises(AlertDataUnavailableError):
            _pick_series_result(2, _rows(2), _query(3))

    def test_an_index_within_the_results_picks_that_row(self):
        assert _pick_series_result(1, _rows(2), _query(2, formulas=["A", "B"]))["label"] == "row 1"

    @parameterized.expand(
        [
            # The runner groups compare-mode rows by formula, but lists every series' current row first.
            (
                "formulas",
                _query(2, formulas=["A", "B"]),
                [(0, "current"), (0, "previous"), (1, "current"), (1, "previous")],
            ),
            ("series", _query(2), [(0, "current"), (1, "current"), (0, "previous"), (1, "previous")]),
        ]
    )
    def test_compare_mode_picks_the_current_row_of_the_chosen_result(self, _name, query, layout):
        rows = InsightResult(
            result=[
                {"label": f"{order} {period}", "order": order, "compare_label": period} for order, period in layout
            ],
            last_refresh=None,
            cache_key="",
            is_cached=False,
            timezone="UTC",
        )
        compare_query = query.model_copy(update={"compareFilter": CompareFilter(compare=True)})

        assert _pick_series_result(1, rows, compare_query)["label"] == "1 current"
