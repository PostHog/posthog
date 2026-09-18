import time_machine
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import HogQLAlertConfig

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight

from products.alerts.backend.evaluation.contract import AlertDataUnavailableError
from products.alerts.backend.evaluation.detector import evaluate_with_detector
from products.alerts.backend.evaluation.hogql import HogQLExtractor, extract_hogql_detector_series
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.models import Insight


class TestHogQLExtractorFiltersPlaceholder(APIBaseTest, ClickhouseDestroyTablesMixin):
    """Alert evaluation runs without any dashboard context, so a query using the ``{filters}``
    placeholder must resolve from the filters saved on the query itself (or to a no-op when
    none are saved) — never error. Pins that an alerted SQL insight using ``{filters}`` keeps
    evaluating, and which rows it sees."""

    def _evaluate(self, hogql_source: dict) -> float | None:
        insight = Insight.objects.create(
            team=self.team,
            query={"kind": "DataVisualizationNode", "source": hogql_source},
        )
        alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=insight,
            name="filters placeholder alert",
            condition={"type": "absolute_value"},
            config={"type": "HogQLAlertConfig", "evaluation": "last_row"},
            calculation_interval="daily",
        )
        result = HogQLExtractor().extract(
            alert, insight, hogql_source, ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
        )
        assert len(result.series) == 1
        return result.series[0].points[result.series[0].current_index].value

    def test_filters_placeholder_with_and_without_saved_filters(self) -> None:
        with time_machine.travel("2026-06-12T12:00:00Z", tick=False):
            for i in range(3):
                _create_event(
                    team=self.team, event="signup", distinct_id=f"recent_{i}", timestamp="2026-06-11T12:00:00Z"
                )
            for i in range(2):
                _create_event(team=self.team, event="signup", distinct_id=f"old_{i}", timestamp="2026-06-01T12:00:00Z")
            flush_persons_and_events()

            # Saved filters resolve the placeholder: only the 3 events within the date range count.
            assert (
                self._evaluate(
                    {
                        "kind": "HogQLQuery",
                        "query": "SELECT count() FROM events WHERE {filters}",
                        "filters": {"dateRange": {"date_from": "-7d"}},
                    }
                )
                == 3.0
            )

            # No saved filters: the placeholder resolves to a no-op and all rows count.
            assert (
                self._evaluate(
                    {
                        "kind": "HogQLQuery",
                        "query": "SELECT count() FROM events WHERE {filters}",
                    }
                )
                == 5.0
            )


class TestHogQLDetectorPagination(APIBaseTest):
    @parameterized.expand(
        [
            ("last_row", 5, "", "paginated"),
            ("last_row", 120, "", "paginated"),
            ("first_row", 120, "", "at least 121 rows"),
            ("first_row", 5, "", None),
            ("last_row", 120, " LIMIT 180", None),
            ("first_row", 120, " LIMIT 180", None),
        ]
    )
    def test_detector_checks_paginated_history(self, evaluation, window, sql_limit, expected_error):
        direction = "DESC" if evaluation == "first_row" else "ASC"
        insight = Insight.objects.create(
            team=self.team,
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": f"SELECT arrayJoin(range(180)) AS value ORDER BY value {direction}{sql_limit}",
                },
            },
        )
        mode = ExecutionMode.CALCULATE_BLOCKING_ALWAYS
        calculation = calculate_for_query_based_insight(insight, team=self.team, user=self.user, execution_mode=mode)
        assert len(calculation.result) == (180 if sql_limit else 100)
        assert calculation.has_more is (None if sql_limit else True)
        config = HogQLAlertConfig(type="HogQLAlertConfig", evaluation=evaluation, column="value")
        detector = {"type": "mad", "threshold": 0.95, "window": window}
        if expected_error:
            with self.assertRaisesRegex(AlertDataUnavailableError, expected_error):
                extract_hogql_detector_series(insight, self.team, config, detector, user=self.user, execution_mode=mode)
        else:
            result = extract_hogql_detector_series(
                insight, self.team, config, detector, user=self.user, execution_mode=mode
            )
            assert evaluate_with_detector(result, detector).value == 179
