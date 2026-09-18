from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.printer.clickhouse import ClickHousePrinter

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight

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


class TestHogQLLastRowScan(APIBaseTest, ClickhouseDestroyTablesMixin):
    @parameterized.expand(
        [
            ("dense", "UTC", [1, 2, 8]),
            ("long_window", "UTC", [1, 2, 150]),
            ("sparse", "UTC", [1, 8, 12]),
            ("empty", "UTC", []),
            ("fractional_timezone", "Asia/Kathmandu", [1, 2, 8]),
            ("daylight_saving", "Europe/Amsterdam", [1, 2, 8]),
            ("half_hour_dst", "Australia/Lord_Howe", [0.25, 1.75, 2.25, 8]),
        ]
    )
    def test_matches_full_query(self, _name: str, timezone: str, hours: list[float]) -> None:
        self.team.timezone = timezone
        self.team.save(update_fields=["timezone"])
        with time_machine.travel(
            "2026-10-03T16:00:00Z" if _name == "half_hour_dst" else "2026-10-25T04:00:00Z", tick=False
        ):
            for index, hour in enumerate(hours):
                for i in range(index + 1):
                    _create_event(
                        team=self.team,
                        event="signup",
                        distinct_id=f"actor-{hour}-{i}",
                        timestamp=(datetime.now(UTC) - timedelta(hours=hour)).isoformat(),
                    )
            # The exclusive upper bound must not contribute to the latest bucket.
            _create_event(team=self.team, event="signup", distinct_id="at-end", timestamp=datetime.now(UTC).isoformat())
            flush_persons_and_events()
            source = {
                "kind": "HogQLQuery",
                "query": """SELECT toStartOfHour(timestamp) AS bucket, count() AS value FROM events
                    WHERE timestamp >= toStartOfHour(now()) - INTERVAL 48 HOUR
                      AND timestamp < toStartOfHour(now()) GROUP BY bucket ORDER BY bucket ASC""",
            }
            if _name == "long_window":
                source["query"] = source["query"].replace("48 HOUR", "336 HOUR") + " LIMIT 1000"
            insight = Insight.objects.create(team=self.team, query=source)
            alert = AlertConfiguration.objects.create(
                team=self.team,
                insight=insight,
                name="hourly count threshold",
                condition={"type": "absolute_value"},
                config={
                    "type": "HogQLAlertConfig",
                    "evaluation": "last_row",
                    "column": "value",
                    "label_column": "bucket",
                },
                calculation_interval="hourly",
            )
            mode = ExecutionMode.CALCULATE_BLOCKING_ALWAYS
            original_visit_call = ClickHousePrinter.visit_call

            def frozen_clock(printer: ClickHousePrinter, node: ast.Call) -> str:
                # time_machine freezes Python, not the ClickHouse server clock.
                if node.name == "now":
                    node = ast.Call(
                        name="toDateTime",
                        args=[
                            ast.Constant(
                                value=datetime.now(UTC).astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M:%S")
                            ),
                            ast.Constant(value=timezone),
                        ],
                    )
                return original_visit_call(printer, node)

            clock_patch = patch.object(ClickHousePrinter, "visit_call", frozen_clock)
            clock_patch.start()
            self.addCleanup(clock_patch.stop)
            full = calculate_for_query_based_insight(insight, team=self.team, user=None, execution_mode=mode)
            assert isinstance(full.result, list)
            with patch(
                "products.alerts.backend.evaluation.hogql.calculate_for_query_based_insight",
                wraps=calculate_for_query_based_insight,
            ) as calculator:
                result = HogQLExtractor().extract(alert, insight, source, mode)
            assert [p.value for p in result.series[0].points] == (
                [float(row[1]) for row in full.result[-2:]] or [0.0, 0.0]
            )
            if full.result:
                assert result.series[0].label == str(full.result[-1][0])
            assert calculator.call_args_list[0].kwargs["query_override"] is not None
            assert calculator.call_count == (
                1 if _name in ("dense", "long_window", "fractional_timezone", "daylight_saving") else 2
            )
            assert insight.query == source
