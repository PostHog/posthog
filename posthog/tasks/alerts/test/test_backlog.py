from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.schema import AlertCalculationInterval

from posthog.redis import get_client
from posthog.tasks.alerts.backlog import UnstartedDueAlerts, unstarted_due_insight_alerts
from posthog.temporal.alerts.admission import INFLIGHT_KEY, admit_evaluation_slots

from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.models import Insight

NOW = datetime(2026, 11, 9, 14, 0, tzinfo=UTC)


@time_machine.travel(NOW, tick=False)
class TestUnstartedDueInsightAlerts(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        get_client().delete(INFLIGHT_KEY)
        self.addCleanup(get_client().delete, INFLIGHT_KEY)
        self.insight = Insight.objects.create(team=self.team, name="insight")

    def _alert(self, interval: AlertCalculationInterval, next_check_at: datetime) -> AlertConfiguration:
        return AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="alert",
            condition={"type": "absolute_value"},
            calculation_interval=interval.value,
            next_check_at=next_check_at,
            created_by=self.user,
        )

    def _by_interval(self) -> dict[str, UnstartedDueAlerts]:
        return {entry.calculation_interval: entry for entry in unstarted_due_insight_alerts(NOW)}

    def test_counts_only_due_alerts_without_a_running_check(self) -> None:
        self._alert(AlertCalculationInterval.HOURLY, NOW - timedelta(hours=4))
        self._alert(AlertCalculationInterval.HOURLY, NOW - timedelta(minutes=10))
        running = self._alert(AlertCalculationInterval.HOURLY, NOW - timedelta(hours=6))
        self._alert(AlertCalculationInterval.HOURLY, NOW + timedelta(minutes=30))
        admit_evaluation_slots([str(running.id)], limit=10, expires_at=NOW.timestamp() + 600)

        backlog = self._by_interval()

        assert backlog[AlertCalculationInterval.HOURLY.value] == UnstartedDueAlerts(
            calculation_interval=AlertCalculationInterval.HOURLY.value,
            count=2,
            oldest_due_age_seconds=4 * 3600,
        )
        assert {interval.value for interval in AlertCalculationInterval} <= backlog.keys()
        assert backlog[AlertCalculationInterval.DAILY.value].count == 0

    def test_counts_running_checks_when_the_slot_set_cannot_be_read(self) -> None:
        self._alert(AlertCalculationInterval.DAILY, NOW - timedelta(hours=1))

        with patch("posthog.temporal.alerts.admission.inflight_alert_ids", side_effect=ConnectionError):
            backlog = self._by_interval()

        assert backlog[AlertCalculationInterval.DAILY.value].count == 1
