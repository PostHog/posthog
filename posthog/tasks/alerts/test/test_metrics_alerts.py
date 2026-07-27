import datetime as dt
from typing import Any, Optional

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

import dateutil.parser
from parameterized import parameterized

from posthog.schema import AlertCalculationInterval, AlertState

from posthog.api.test.dashboards import DashboardAPI
from posthog.models.instance_setting import set_instance_setting
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.tasks.alerts.test.alert_check_helpers import run_alert_check

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.metrics.backend.facade.testing import seed_metric

# 08:55 — the 08:00 hourly bucket is still accumulating; 07:00 is the last complete one.
FROZEN_TIME = dateutil.parser.parse("2026-07-01T08:55:00.000Z")


def _metrics_flag_only(flag: str, *args: Any, **kwargs: Any) -> bool:
    return flag == "metrics"


@freeze_time(FROZEN_TIME)
@patch("products.alerts.backend.api.alert.posthoganalytics.feature_enabled", side_effect=_metrics_flag_only)
@patch("posthog.tasks.alerts.utils.send_notifications_for_errors")
@patch("posthog.tasks.alerts.utils.send_notifications_for_breaches")
class TestMetricsAlerts(APIBaseTest, ClickhouseTestMixin):
    def setUp(self) -> None:
        super().setUp()
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        # metrics1 is not truncated between tests, so a per-test metric name keeps tests isolated.
        self.metric_name = f"queue.depth.{self._testMethodName}"

    def create_metrics_insight(self, group_by: Optional[list[str]] = None) -> dict:
        clause: dict[str, Any] = {"name": "a", "metricName": self.metric_name, "aggregation": "avg"}
        if group_by:
            clause["groupBy"] = [{"key": key} for key in group_by]
        query_dict = {"kind": "MetricsQuery", "clauses": [clause]}
        return self.dashboard_api.create_insight(data={"name": "metrics insight", "query": query_dict})[1]

    def create_alert(
        self,
        insight: dict,
        lower: Optional[float] = None,
        upper: Optional[float] = None,
        condition_type: str = "absolute_value",
        config: Optional[dict] = None,
        expected_status: int = 201,
        **alert_overrides: Any,
    ) -> dict:
        data = {
            "name": "metrics alert",
            "insight": insight["id"],
            "subscribed_users": [self.user.id],
            "config": config or {"type": "MetricsAlertConfig"},
            "condition": {"type": condition_type},
            "calculation_interval": AlertCalculationInterval.DAILY,
            "threshold": {"configuration": {"type": "absolute", "bounds": {"lower": lower, "upper": upper}}},
            **alert_overrides,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", data=data)
        assert response.status_code == expected_status, response.json()
        return response.json()

    def seed_gauge(self, values_by_hour: dict[int, float], labels: Optional[dict[str, str]] = None) -> None:
        seed_metric(
            team_id=self.team.pk,
            metric_name=self.metric_name,
            metric_type="gauge",
            points=[
                (dt.datetime(2026, 7, 1, hour, 30, tzinfo=dt.UTC), value) for hour, value in values_by_hour.items()
            ],
            labels=labels or {},
        )

    @parameterized.expand(
        [
            # (name, seeded value, lower, upper, expected_state, expected_message_fragment)
            ("lower_breach_fires", 5.0, 10.0, None, AlertState.FIRING, "is less than lower threshold (10.0)"),
            ("upper_breach_fires", 50.0, None, 20.0, AlertState.FIRING, "is more than upper threshold (20.0)"),
            ("within_bounds_not_firing", 15.0, 10.0, 20.0, AlertState.NOT_FIRING, None),
        ]
    )
    def test_absolute_threshold(
        self,
        mock_send_breaches: MagicMock,
        mock_send_errors: MagicMock,
        mock_feature_enabled: MagicMock,
        _name: str,
        seeded_value: float,
        lower: Optional[float],
        upper: Optional[float],
        expected_state: AlertState,
        expected_fragment: Optional[str],
    ) -> None:
        # Two complete hourly buckets; the default anchor is the second-to-last observed bucket (07:00).
        self.seed_gauge({6: seeded_value, 7: seeded_value, 8: seeded_value})
        insight = self.create_metrics_insight()
        alert = self.create_alert(insight, lower=lower, upper=upper)
        assert alert["state"] == AlertState.NOT_FIRING

        run_alert_check(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == expected_state
        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == seeded_value
        if expected_fragment is None:
            mock_send_breaches.assert_not_called()
        else:
            mock_send_breaches.assert_called_once()
            breach_messages = mock_send_breaches.call_args.args[1]
            assert any(expected_fragment in message for message in breach_messages), breach_messages

    def test_empty_metrics_result_evaluates_as_zero(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock, mock_feature_enabled: MagicMock
    ) -> None:
        # No data at all: the alert must still evaluate (as 0) and fire a lower-bound breach,
        # not error out or silently skip.
        insight = self.create_metrics_insight()
        alert = self.create_alert(insight, lower=1.0)

        run_alert_check(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.FIRING
        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 0
        assert alert_check.error is None

    def test_group_by_fires_on_any_breaching_series(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock, mock_feature_enabled: MagicMock
    ) -> None:
        # Two label-sets; only one breaches. Catches an extractor that evaluates only the first series.
        self.seed_gauge({6: 5.0, 7: 5.0}, labels={"container": "small"})
        self.seed_gauge({6: 50.0, 7: 50.0}, labels={"container": "big"})
        insight = self.create_metrics_insight(group_by=["container"])
        alert = self.create_alert(insight, upper=20.0)

        run_alert_check(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.FIRING
        mock_send_breaches.assert_called_once()
        breach_messages = mock_send_breaches.call_args.args[1]
        assert any("big" in message for message in breach_messages), breach_messages

    def test_relative_increase_fires(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock, mock_feature_enabled: MagicMock
    ) -> None:
        # Anchor bucket (06:00) is 5 above the previous bucket (05:00); catches wrong
        # anchor/previous index wiring on the observed-bucket grid.
        self.seed_gauge({5: 10.0, 6: 15.0, 7: 15.0})
        insight = self.create_metrics_insight()
        alert = self.create_alert(insight, upper=4.0, condition_type="relative_increase")

        run_alert_check(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.FIRING
        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 5.0

    def test_create_rejected_when_metrics_flag_disabled(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock, mock_feature_enabled: MagicMock
    ) -> None:
        mock_feature_enabled.side_effect = None
        mock_feature_enabled.return_value = False
        insight = self.create_metrics_insight()
        response = self.create_alert(insight, lower=1.0, expected_status=400)
        assert "not enabled" in response["detail"].lower() or "not supported" in response["detail"].lower()

    def test_simulate_rejected_when_metrics_flag_disabled(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock, mock_feature_enabled: MagicMock
    ) -> None:
        # The simulate endpoint must apply the same feature gate as create/update — otherwise a
        # flag-off account gets the ungated unsupported-detector error instead of the gated one.
        insight = self.create_metrics_insight()
        mock_feature_enabled.side_effect = None
        mock_feature_enabled.return_value = False
        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts/simulate",
            data={
                "insight": insight["id"],
                "detector_config": {"type": "zscore", "threshold": 0.9, "window": 10},
            },
        )
        assert response.status_code == 400, response.json()
        assert "not enabled" in str(response.json()).lower()

    def test_simulate_rejects_metrics_insight_with_flag_on(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock, mock_feature_enabled: MagicMock
    ) -> None:
        # Metrics has no detector extractor: simulation must 400 cleanly via the registry, not 500.
        insight = self.create_metrics_insight()
        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts/simulate",
            data={
                "insight": insight["id"],
                "detector_config": {"type": "zscore", "threshold": 0.9, "window": 10},
            },
        )
        assert response.status_code == 400, response.json()
        assert "isn't supported for MetricsQuery" in str(response.json())

    @parameterized.expand(
        [
            # An alert executes the metrics query as created_by and delivers values in
            # notifications, so a programmatic token needs the metrics data scope too —
            # without this, alert:write alone is a metrics-read oracle.
            ("alert_write_only_rejected", ["alert:write"], 403),
            ("alert_write_with_metrics_read_allowed", ["alert:write", "metrics:read"], 201),
        ]
    )
    def test_api_key_metrics_scope_enforcement(
        self,
        mock_send_breaches: MagicMock,
        mock_send_errors: MagicMock,
        mock_feature_enabled: MagicMock,
        _name: str,
        scopes: list[str],
        expected_status: int,
    ) -> None:
        insight = self.create_metrics_insight()
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="metrics alerts test",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=scopes,
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "metrics alert",
                "insight": insight["id"],
                "subscribed_users": [self.user.id],
                "config": {"type": "MetricsAlertConfig"},
                "condition": {"type": "absolute_value"},
                "calculation_interval": AlertCalculationInterval.DAILY,
                "threshold": {"configuration": {"type": "absolute", "bounds": {"lower": 1.0, "upper": None}}},
            },
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )
        assert response.status_code == expected_status, response.json()
        if expected_status == 403:
            assert "metrics:read" in str(response.json())

    @parameterized.expand(
        [
            # Read paths must hide metric alert results (last_value, check history, breach labels)
            # from tokens lacking the metrics data scope — otherwise alert:read alone reads values
            # from alerts a session user scheduled, bypassing the write-side gate.
            ("alert_read_only_hidden", ["alert:read"], False),
            ("alert_read_with_metrics_read_visible", ["alert:read", "metrics:read"], True),
        ]
    )
    def test_api_key_read_paths_gate_metrics_alerts(
        self,
        mock_send_breaches: MagicMock,
        mock_send_errors: MagicMock,
        mock_feature_enabled: MagicMock,
        _name: str,
        scopes: list[str],
        visible: bool,
    ) -> None:
        insight = self.create_metrics_insight()
        alert = self.create_alert(insight, lower=1.0)  # session-created, so no write-side scope gate
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="metrics alerts read test",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=scopes,
        )
        authorization = f"Bearer {key_value}"

        list_response = self.client.get(f"/api/projects/{self.team.id}/alerts", HTTP_AUTHORIZATION=authorization)
        assert list_response.status_code == 200, list_response.json()
        listed_ids = {result["id"] for result in list_response.json()["results"]}
        assert (alert["id"] in listed_ids) is visible

        detail_response = self.client.get(
            f"/api/projects/{self.team.id}/alerts/{alert['id']}", HTTP_AUTHORIZATION=authorization
        )
        assert detail_response.status_code == (200 if visible else 404), detail_response.json()

        # Thresholds (nested under the insight) embed full alerts including check values, so they
        # must be gated the same way.
        thresholds_response = self.client.get(
            f"/api/projects/{self.team.id}/insights/{insight['id']}/thresholds", HTTP_AUTHORIZATION=authorization
        )
        assert thresholds_response.status_code == 200, thresholds_response.json()
        threshold_alert_ids = {
            nested["id"] for result in thresholds_response.json()["results"] for nested in result.get("alerts", [])
        }
        assert (alert["id"] in threshold_alert_ids) is visible

    @parameterized.expand(
        [
            (
                "trends_config_on_metrics_insight",
                {"type": "TrendsAlertConfig", "series_index": 0},
                {},
                "not supported",
            ),
            (
                "detector_config_rejected",
                {"type": "MetricsAlertConfig"},
                {"detector_config": {"type": "zscore", "threshold": 0.9, "window": 10}},
                "anomaly detection",
            ),
            (
                "ongoing_interval_requires_upper_bound",
                {"type": "MetricsAlertConfig", "check_ongoing_interval": True},
                {},
                "upper threshold",
            ),
        ]
    )
    def test_invalid_configs_rejected(
        self,
        mock_send_breaches: MagicMock,
        mock_send_errors: MagicMock,
        mock_feature_enabled: MagicMock,
        _name: str,
        config: dict,
        alert_overrides: dict,
        expected_fragment: str,
    ) -> None:
        insight = self.create_metrics_insight()
        response = self.create_alert(insight, lower=1.0, config=config, expected_status=400, **alert_overrides)
        assert expected_fragment in str(response).lower(), response
