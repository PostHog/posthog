from datetime import UTC, datetime
from typing import Any, cast

import pytest
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


class TestAlert15MinuteInterval(APIBaseTest):
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
            "name": "15 min alert",
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"lower": 0}}},
            "calculation_interval": AlertCalculationInterval.EVERY_15_MINUTES,
        }
        payload.update(overrides)
        return payload

    def _enable_high_frequency_alerts(self) -> None:
        self.organization.available_product_features = [
            *(self.organization.available_product_features or []),
            {"key": AvailableFeature.HIGH_FREQUENCY_ALERTS, "name": "High frequency alerts"},
        ]
        self.organization.save()

    def test_create_every_15_minutes_rejected_without_billing_entitlement(self) -> None:
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request())
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Boost, Scale, or Enterprise" in str(response.json())

    def test_create_every_15_minutes_succeeds_with_entitlement(self) -> None:
        self._enable_high_frequency_alerts()
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request())
        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert response.json()["calculation_interval"] == AlertCalculationInterval.EVERY_15_MINUTES

    def test_patch_every_15_minutes_succeeds_with_entitlement(self) -> None:
        self._enable_high_frequency_alerts()
        create_response = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request())
        alert_id = create_response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{alert_id}",
            {"name": "updated 15 min alert"},
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["name"] == "updated 15 min alert"
        assert response.json()["calculation_interval"] == AlertCalculationInterval.EVERY_15_MINUTES

    def test_patch_existing_every_15_minutes_rejected_after_entitlement_removed(self) -> None:
        self._enable_high_frequency_alerts()
        create_response = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request())
        alert_id = create_response.json()["id"]

        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{alert_id}",
            {"name": "still 15 min"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Boost, Scale, or Enterprise" in str(response.json())


class TestAlert15MinuteScheduling:
    def test_calculation_interval_to_order_ranks_every_15_minutes_before_hourly(self) -> None:
        assert calculation_interval_to_order(AlertCalculationInterval.EVERY_15_MINUTES) < calculation_interval_to_order(
            AlertCalculationInterval.HOURLY
        )

    def test_alert_calculation_interval_to_relativedelta_every_15_minutes(self) -> None:
        delta = alert_calculation_interval_to_relativedelta(AlertCalculationInterval.EVERY_15_MINUTES)
        assert delta.minutes == 15

    def test_next_check_time_advances_by_15_minutes(self) -> None:
        alert = MagicMock(spec=AlertConfiguration)
        alert.calculation_interval = AlertCalculationInterval.EVERY_15_MINUTES
        alert.next_check_at = datetime(2026, 4, 6, 14, 0, 0, tzinfo=UTC)
        alert.team = MagicMock()
        alert.team.timezone = "UTC"
        alert.schedule_restriction = None
        alert.skip_weekend = False

        with freeze_time("2026-04-06T14:00:00Z"):
            assert next_check_time(alert) == datetime(2026, 4, 6, 14, 15, 0, tzinfo=UTC)

    def test_calculation_interval_to_order_raises_for_none(self) -> None:
        with pytest.raises(ValueError, match="Invalid alert calculation interval: None"):
            calculation_interval_to_order(None)

    def test_calculation_interval_to_order_raises_for_unknown_interval(self) -> None:
        with pytest.raises(ValueError, match="Unhandled alert calculation interval"):
            calculation_interval_to_order(cast(AlertCalculationInterval, "every_5_minutes"))

    def test_alert_calculation_interval_to_relativedelta_raises_for_unknown_interval(self) -> None:
        with pytest.raises(ValueError, match="Unhandled alert calculation interval"):
            alert_calculation_interval_to_relativedelta(cast(AlertCalculationInterval, "every_5_minutes"))
