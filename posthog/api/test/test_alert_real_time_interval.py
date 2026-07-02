from datetime import UTC, datetime
from typing import Any

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock

from rest_framework import status

from posthog.schema import AlertCalculationInterval, AlertConditionType, InsightThresholdType

from posthog.constants import AvailableFeature
from posthog.tasks.alerts.utils import (
    alert_calculation_interval_to_relativedelta,
    calculation_interval_to_order,
    next_check_time,
)

from products.alerts.backend.models.alert import AlertConfiguration


class TestAlertRealTimeInterval(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.default_insight_data: dict[str, Any] = {
            "query": {
                "kind": "TrendsQuery",
                "series": [
                    {
                        "kind": "EventsNode",
                        "event": "$pageview",
                    }
                ],
                "trendsFilter": {"display": "BoldNumber"},
            },
        }
        self.insight = self.client.post(f"/api/projects/{self.team.id}/insights", data=self.default_insight_data).json()

    def _creation_request(self, **overrides: Any) -> dict[str, Any]:
        payload = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "name": "real time alert",
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"lower": 0}}},
            "calculation_interval": AlertCalculationInterval.REAL_TIME,
        }
        payload.update(overrides)
        return payload

    def _enable_real_time_alerts(self, limit: int | None = None) -> None:
        feature: dict[str, Any] = {"key": AvailableFeature.REAL_TIME_ALERTS, "name": "Real-time alerts"}
        if limit is not None:
            feature["limit"] = limit
        self.organization.available_product_features = [
            *(self.organization.available_product_features or []),
            feature,
        ]
        self.organization.save()

    def test_create_real_time_rejected_without_billing_entitlement(self) -> None:
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request())
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Scale or Enterprise" in str(response.json())

    def test_create_real_time_succeeds_with_entitlement(self) -> None:
        self._enable_real_time_alerts()
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request())
        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert response.json()["calculation_interval"] == AlertCalculationInterval.REAL_TIME

    def test_patch_existing_real_time_rejected_after_entitlement_removed(self) -> None:
        self._enable_real_time_alerts()
        create_response = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request())
        alert_id = create_response.json()["id"]

        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{alert_id}",
            {"name": "still real time"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Scale or Enterprise" in str(response.json())

    def test_create_real_time_rejected_when_limit_reached(self) -> None:
        self._enable_real_time_alerts(limit=1)
        first = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request())
        assert first.status_code == status.HTTP_201_CREATED, first.content

        second = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request(name="second"))
        assert second.status_code == status.HTTP_400_BAD_REQUEST
        assert "limit of 1 real-time alerts" in str(second.json())

    def test_real_time_limit_ignores_other_intervals(self) -> None:
        self._enable_real_time_alerts(limit=1)
        daily = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            self._creation_request(name="daily", calculation_interval=AlertCalculationInterval.DAILY),
        )
        assert daily.status_code == status.HTTP_201_CREATED, daily.content

        response = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request())
        assert response.status_code == status.HTTP_201_CREATED, response.content


class TestAlertRealTimeScheduling:
    def test_calculation_interval_to_order_ranks_real_time_first(self) -> None:
        assert calculation_interval_to_order(AlertCalculationInterval.REAL_TIME) < calculation_interval_to_order(
            AlertCalculationInterval.EVERY_15_MINUTES
        )

    def test_alert_calculation_interval_to_relativedelta_real_time(self) -> None:
        delta = alert_calculation_interval_to_relativedelta(AlertCalculationInterval.REAL_TIME)
        assert delta.minutes == 2

    def test_next_check_time_advances_by_2_minutes(self) -> None:
        alert = MagicMock(spec=AlertConfiguration)
        alert.calculation_interval = AlertCalculationInterval.REAL_TIME
        alert.next_check_at = datetime(2026, 4, 6, 14, 0, 0, tzinfo=UTC)
        alert.team = MagicMock()
        alert.team.timezone = "UTC"
        alert.schedule_restriction = None
        alert.skip_weekend = False

        with freeze_time("2026-04-06T14:00:00Z"):
            assert next_check_time(alert) == datetime(2026, 4, 6, 14, 2, 0, tzinfo=UTC)
