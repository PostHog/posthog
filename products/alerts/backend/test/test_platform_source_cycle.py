import time
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import ChartDisplayType, EventsNode, IntervalType, TrendsFilter, TrendsQuery

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import get_query_tags
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseClusterMemoryLimitExceeded
from posthog.models.scoping import team_scope
from posthog.redis import get_client
from posthog.schema_enums import AlertCalculationInterval
from posthog.tasks.alerts.utils import AlertEvaluationResult

from products.alerts.backend.evaluation.contract import AlertExtractionError
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, Threshold
from products.alerts.backend.platform_source_cycle import (
    CAPACITY_REJECTED,
    INFLIGHT_KEY,
    evaluate_insight_check,
    plan_insight_batch,
)
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import record_outcomes, slot_of
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    PlatformAlertOutcome,
    PlatformConfigurationSnapshot,
    SourceKind,
)
from products.product_analytics.backend.facade.models import Insight

_MODULE = "products.alerts.backend.platform_source_cycle"
# A Wednesday, so no weekend rule applies.
CUTOFF = datetime(2026, 9, 16, 10, tzinfo=UTC)


class TestPlatformInsightEvaluation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        get_client().delete(INFLIGHT_KEY)
        self.addCleanup(get_client().delete, INFLIGHT_KEY)

    def _alert(self, **overrides: Any) -> AlertConfiguration:
        insight = Insight.objects.create(
            team=self.team,
            name="insight",
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                interval=IntervalType.DAY,
                trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
            ).model_dump(),
        )
        threshold = Threshold.objects.create(
            team=self.team, insight=insight, configuration={"type": "absolute", "bounds": {"upper": 100.0}}
        )
        fields: dict[str, Any] = {
            "team": self.team,
            "insight": insight,
            "name": "alert",
            "calculation_interval": AlertCalculationInterval.DAILY.value,
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "condition": {"type": "absolute_value"},
            "threshold": threshold,
            "next_check_at": CUTOFF - timedelta(minutes=1),
        }
        fields.update(overrides)
        return AlertConfiguration.objects.create(**fields)

    def _copy(self, alert: AlertConfiguration | None) -> PlatformConfigurationSnapshot:
        with team_scope(self.team.id):
            return platform_testing.create_configuration(
                team_id=self.team.id,
                name="alert",
                source_kind=SourceKind.INSIGHT,
                source_config={},
                check_interval_minutes=60 * 24,
                recurrence_unit="day",
                next_check_at=CUTOFF - timedelta(minutes=1),
                legacy_configuration_id=alert.id if alert else None,
            )

    def _evaluate(
        self, configuration: PlatformConfigurationSnapshot, *, result: Any = None
    ) -> tuple[PlatformAlertOutcome | None, MagicMock]:
        slot = slot_of(configuration.next_check_at, CUTOFF)
        expires_at = time.time() + 3600
        assert plan_insight_batch(self.team.id, slot, CUTOFF, expires_at=expires_at) == (str(configuration.id),)
        side_effect = result if isinstance(result, Exception) else None
        returned = result if isinstance(result, AlertEvaluationResult) else None
        with patch(f"{_MODULE}.check_alert_for_insight", side_effect=side_effect, return_value=returned) as query:
            outcome = evaluate_insight_check(
                self.team.id, slot, CUTOFF, str(configuration.id), held_until=expires_at, evaluation_id="test"
            )
        return outcome, query

    def test_a_breach_fires_on_the_platform_and_leaves_the_production_alert_alone(self) -> None:
        alert = self._alert()
        before = AlertConfiguration.objects.values("state", "next_check_at", "last_checked_at").get(id=alert.id)
        configuration = self._copy(alert)

        outcome, _ = self._evaluate(configuration, result=AlertEvaluationResult(value=150.0, breaches=["above 100"]))
        assert outcome is not None
        assert get_query_tags().ch_user == ClickHouseUser.ALERTS_PLATFORM_INSIGHT
        record_outcomes(self.team.id, (outcome,), CUTOFF)

        assert (outcome.kind, outcome.value, outcome.evaluation_key) == (
            AlertEventKind.FIRING,
            150.0,
            f"slot:{slot_of(configuration.next_check_at, CUTOFF)}",
        )
        with team_scope(self.team.id):
            platform_alert = platform_testing.alert_for(configuration.id)
        assert platform_alert is not None and platform_alert.state == "firing"
        assert AlertConfiguration.objects.values("state", "next_check_at", "last_checked_at").get(id=alert.id) == before
        assert not AlertCheck.objects.filter(alert_configuration=alert).exists()

    @parameterized.expand(
        [
            ("real_time", {"calculation_interval": AlertCalculationInterval.REAL_TIME.value}, "not_firing"),
            ("detector", {"detector_config": {"type": "zscore"}}, "not_firing"),
            ("disabled", {"enabled": False}, "not_firing"),
            ("snoozed", {"snoozed_until": CUTOFF + timedelta(hours=1)}, "snoozed"),
        ]
    )
    def test_a_check_production_would_not_run_is_recorded_without_a_query(
        self, _name: str, overrides: dict[str, Any], state: str
    ) -> None:
        outcome, query = self._evaluate(self._copy(self._alert(**overrides)))

        query.assert_not_called()
        assert outcome is not None
        assert (outcome.kind, outcome.new_state, outcome.disable) == (AlertEventKind.CHECK, state, False)

    def test_a_copy_whose_production_alert_is_gone_is_disabled(self) -> None:
        outcome, query = self._evaluate(self._copy(None))

        query.assert_not_called()
        assert outcome is not None and outcome.disable

    @parameterized.expand(
        [
            ("too_many_queries", ClickHouseAtCapacity()),
            ("cluster_memory_full", ClickHouseClusterMemoryLimitExceeded()),
        ]
    )
    def test_a_check_clickhouse_refuses_for_load_leaves_the_alert_as_it_was(self, _name: str, error: Exception) -> None:
        outcome, _ = self._evaluate(self._copy(self._alert()), result=error)

        assert outcome is not None
        assert (outcome.kind, outcome.new_state, outcome.error_message, outcome.disable) == (
            AlertEventKind.CHECK,
            "not_firing",
            CAPACITY_REJECTED,
            False,
        )

    def test_an_alert_production_cannot_evaluate_as_configured_errors_and_is_disabled(self) -> None:
        outcome, _ = self._evaluate(self._copy(self._alert()), result=AlertExtractionError("bad query shape"))

        assert outcome is not None
        assert (outcome.kind, outcome.new_state, outcome.disable) == (AlertEventKind.ERRORED, "errored", True)

    @override_settings(ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_EVALUATIONS=1)
    def test_the_pool_defers_what_it_cannot_hold_until_a_check_frees_its_slot(self) -> None:
        first, second = self._copy(self._alert()), self._copy(self._alert())
        slot = slot_of(first.next_check_at, CUTOFF)
        expires_at = time.time() + 3600

        (admitted,) = plan_insight_batch(self.team.id, slot, CUTOFF, expires_at=expires_at)
        assert plan_insight_batch(self.team.id, slot, CUTOFF, expires_at=expires_at + 60) == ()

        with patch(f"{_MODULE}.check_alert_for_insight", return_value=AlertEvaluationResult(value=1.0, breaches=[])):
            evaluate_insight_check(self.team.id, slot, CUTOFF, admitted, held_until=expires_at, evaluation_id="test")

        assert len(plan_insight_batch(self.team.id, slot, CUTOFF, expires_at=expires_at + 60)) == 1
        assert {str(first.id), str(second.id)} >= {admitted}
