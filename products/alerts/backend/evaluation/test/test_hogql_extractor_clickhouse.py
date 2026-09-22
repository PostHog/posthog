import time_machine
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events

from posthog.api.services.query import ExecutionMode

from products.alerts.backend.evaluation.contract import AlertExtractionError
from products.alerts.backend.evaluation.hogql import HogQLExtractor
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


class TestHogQLExtractorDefaultRowLimit(APIBaseTest, ClickhouseDestroyTablesMixin):
    """A query that sets no LIMIT is cut at the default row count and nothing says so, so last-row
    evaluation would grade the end of a page instead of the newest row. Pins that the truncation
    reaches the extractor as ``has_more`` on the real query path, which no mocked test can show."""

    def _evaluate(self, query: str) -> float | None:
        insight = Insight.objects.create(
            team=self.team,
            query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": query}},
        )
        alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=insight,
            name="row limit alert",
            condition={"type": "absolute_value"},
            config={"type": "HogQLAlertConfig", "evaluation": "last_row"},
            calculation_interval="daily",
        )
        result = HogQLExtractor().extract(
            alert, insight, insight.query, ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
        )
        return result.series[0].points[result.series[0].current_index].value

    def test_query_without_limit_is_rejected(self) -> None:
        with self.assertRaisesMessage(AlertExtractionError, "no LIMIT"):
            self._evaluate("SELECT number FROM numbers(200) ORDER BY number")

    def test_query_with_its_own_limit_evaluates_the_last_row(self) -> None:
        assert self._evaluate("SELECT number FROM numbers(200) ORDER BY number LIMIT 200") == 199.0

    def test_short_result_without_a_limit_evaluates_normally(self) -> None:
        # Nothing was cut, so a LIMIT-less query under the default row count still evaluates.
        assert self._evaluate("SELECT number FROM numbers(3) ORDER BY number") == 2.0
