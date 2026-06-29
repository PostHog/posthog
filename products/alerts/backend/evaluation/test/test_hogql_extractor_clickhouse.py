from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events

from posthog.api.services.query import ExecutionMode

from products.alerts.backend.evaluation.hogql import HogQLExtractor
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight


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
        with freeze_time("2026-06-12T12:00:00Z"):
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
