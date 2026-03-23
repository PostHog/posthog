from copy import deepcopy
from datetime import datetime
from typing import Any

from posthog.test.base import APIBaseTest, QueryMatchingTest
from unittest import mock

from parameterized import parameterized
from rest_framework import status

from posthog.schema import AlertConditionType, AlertState, InsightThresholdType

from posthog.models import AlertConfiguration
from posthog.models.alert import AlertCheck
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal


class TestAlert(APIBaseTest, QueryMatchingTest):
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

    def test_create_and_delete_alert(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [
                self.user.id,
            ],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "name": "alert name",
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "calculation_interval": "daily",
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)

        expected_alert_json = {
            "calculation_interval": "daily",
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "created_at": mock.ANY,
            "created_by": mock.ANY,
            "enabled": True,
            "id": mock.ANY,
            "insight": mock.ANY,
            "last_notified_at": None,
            "name": "alert name",
            "subscribed_users": mock.ANY,
            "state": "Not firing",
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "detector_config": None,
            "threshold": {
                "configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}},
                "created_at": mock.ANY,
                "id": mock.ANY,
                "name": "",
            },
            "last_checked_at": None,
            "next_check_at": None,
            "snoozed_until": None,
            "skip_weekend": False,
            "last_value": None,
        }
        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert response.json() == expected_alert_json

        alerts = self.client.get(f"/api/projects/{self.team.id}/alerts")
        assert alerts.json()["results"] == [{**expected_alert_json, "checks": []}]

        alert_id = response.json()["id"]
        self.client.delete(f"/api/projects/{self.team.id}/alerts/{alert_id}")

        alerts = self.client.get(f"/api/projects/{self.team.id}/alerts")
        assert len(alerts.json()["results"]) == 0

    def test_incorrect_creation(self) -> None:
        creation_request = {
            "subscribed_users": [
                self.user.id,
            ],
            "threshold": {"configuration": {}},
            "name": "alert name",
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        another_team = Team.objects.create(
            organization=self.organization,
            api_token=self.CONFIG_API_TOKEN + "2",
        )
        another_team_insight = self.client.post(
            f"/api/projects/{another_team.id}/insights", data=self.default_insight_data
        ).json()
        creation_request = {
            "insight": str(another_team_insight["id"]),
            "subscribed_users": [
                self.user.id,
            ],
            "threshold": {"configuration": {}},
            "name": "alert name",
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_and_list_alert(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [
                self.user.id,
            ],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "alert name",
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()

        list = self.client.get(f"/api/projects/{self.team.id}/alerts?insight={self.insight['id']}")
        assert list.status_code == status.HTTP_200_OK
        results = list.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] == alert["id"]

        list_for_another_insight = self.client.get(
            f"/api/projects/{self.team.id}/alerts?insight={self.insight['id'] + 1}"
        )
        assert list_for_another_insight.status_code == status.HTTP_200_OK
        assert len(list_for_another_insight.json()["results"]) == 0

    def test_alert_limit(self) -> None:
        with mock.patch("posthog.api.alert.AlertConfiguration.ALERTS_ALLOWED_ON_FREE_TIER") as alert_limit:
            alert_limit.__get__ = mock.Mock(return_value=1)

            creation_request = {
                "insight": self.insight["id"],
                "subscribed_users": [
                    self.user.id,
                ],
                "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
                "name": "alert name",
            }
            self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)

            alert_2 = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()

            assert alert_2["code"] == "invalid_input"

    def test_alert_is_deleted_on_insight_update(self) -> None:
        another_insight = self.client.post(
            f"/api/projects/{self.team.id}/insights", data=self.default_insight_data
        ).json()
        creation_request = {
            "insight": another_insight["id"],
            "subscribed_users": [
                self.user.id,
            ],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "alert name",
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()

        updated_insight = deepcopy(self.default_insight_data)
        updated_insight["query"]["series"][0]["event"] = "$anotherEvent"
        self.client.patch(
            f"/api/projects/{self.team.id}/insights/{another_insight['id']}",
            data=updated_insight,
        ).json()

        response = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert['id']}")
        # alerts should not be deleted if the new insight version supports alerts
        assert response.status_code == status.HTTP_200_OK

        insight_without_alert_support = deepcopy(self.default_insight_data)
        insight_without_alert_support["query"] = {"kind": "FunnelsQuery", "series": []}
        self.client.patch(
            f"/api/projects/{self.team.id}/insights/{another_insight['id']}",
            data=insight_without_alert_support,
        ).json()

        response = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert['id']}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_alert_cleans_up_hog_functions(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "alert name",
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()
        alert_id = alert["id"]

        linked_hog_function = HogFunction.objects.create(
            team=self.team,
            name="Slack notification for alert",
            type="internal_destination",
            hog="return 1",
            enabled=True,
            filters={
                "events": [{"id": "$insight_alert_firing", "type": "events"}],
                "properties": [{"key": "alert_id", "value": alert_id, "operator": "exact", "type": "event"}],
            },
        )
        unrelated_hog_function = HogFunction.objects.create(
            team=self.team,
            name="Unrelated destination",
            type="internal_destination",
            hog="return 1",
            enabled=True,
            filters={
                "events": [{"id": "$insight_alert_firing", "type": "events"}],
                "properties": [{"key": "alert_id", "value": "some-other-id", "operator": "exact", "type": "event"}],
            },
        )

        self.client.delete(f"/api/projects/{self.team.id}/alerts/{alert_id}")

        linked_hog_function.refresh_from_db()
        assert linked_hog_function.deleted is True
        assert linked_hog_function.enabled is False

        unrelated_hog_function.refresh_from_db()
        assert unrelated_hog_function.deleted is False
        assert unrelated_hog_function.enabled is True

    def test_snooze_alert(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [
                self.user.id,
            ],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "alert name",
            "state": AlertState.FIRING,
        }

        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()
        assert alert["state"] == AlertState.NOT_FIRING

        alert = AlertConfiguration.objects.get(pk=alert["id"])
        alert.state = AlertState.FIRING
        alert.save()

        firing_alert = AlertConfiguration.objects.get(pk=alert.id)
        assert firing_alert.state == AlertState.FIRING

        resolved_alert = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{firing_alert.id}", {"snoozed_until": datetime.now()}
        ).json()
        assert resolved_alert["state"] == AlertState.SNOOZED

        # should also create a new alert check with resolution
        check = AlertCheck.objects.filter(alert_configuration=firing_alert.id).latest("created_at")
        assert check.state == AlertState.SNOOZED

    @parameterized.expand(
        [
            (
                "invalid_condition",
                {"condition": {"type": "bogus"}, "config": {"type": "TrendsAlertConfig", "series_index": 0}},
                "invalid condition",
            ),
            (
                "missing_config_type",
                {"condition": {"type": AlertConditionType.ABSOLUTE_VALUE}, "config": {"series_index": 0}},
                "unsupported alert config type",
            ),
            (
                "relative_condition_on_pie_chart",
                {
                    "condition": {"type": AlertConditionType.RELATIVE_INCREASE},
                    "config": {"type": "TrendsAlertConfig", "series_index": 0},
                },
                "not compatible with non time series",
            ),
            (
                "absolute_with_percentage_threshold",
                {
                    "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
                    "config": {"type": "TrendsAlertConfig", "series_index": 0},
                    "threshold": {"configuration": {"type": InsightThresholdType.PERCENTAGE, "bounds": {}}},
                },
                "absolute value alerts require an absolute threshold",
            ),
        ]
    )
    def test_create_alert_rejects_invalid_config(self, _name, overrides, expected_error_fragment):
        pie_insight_data = deepcopy(self.default_insight_data)
        pie_insight_data["query"]["trendsFilter"]["display"] = "ActionsPie"
        pie_insight = self.client.post(f"/api/projects/{self.team.id}/insights", data=pie_insight_data).json()

        creation_request = {
            "insight": pie_insight["id"],
            "subscribed_users": [self.user.id],
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "alert name",
            **overrides,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert expected_error_fragment in str(response.content).lower()

    @parameterized.expand(
        [
            (
                "invalid_condition_via_patch",
                {"condition": {"type": "bogus"}},
                "invalid condition",
            ),
            (
                "missing_config_type_via_patch",
                {"config": {"series_index": 0}},
                "unsupported alert config type",
            ),
            (
                "absolute_with_percentage_threshold_via_patch",
                {
                    "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
                    "threshold": {"configuration": {"type": InsightThresholdType.PERCENTAGE, "bounds": {}}},
                },
                "absolute value alerts require an absolute threshold",
            ),
        ]
    )
    def test_patch_alert_rejects_invalid_config(self, _name, overrides, expected_error_fragment):
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "alert name",
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()
        assert "id" in alert, alert

        response = self.client.patch(f"/api/projects/{self.team.id}/alerts/{alert['id']}", overrides)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert expected_error_fragment in str(response.content).lower()


class TestAlertSimulate(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.insight_data: dict[str, Any] = {
            "query": {
                "kind": "TrendsQuery",
                "series": [
                    {
                        "kind": "EventsNode",
                        "event": "$pageview",
                    }
                ],
                "trendsFilter": {"display": "ActionsLineGraph"},
                "interval": "day",
            },
        }
        self.insight = self.client.post(f"/api/projects/{self.team.id}/insights", data=self.insight_data).json()

    @mock.patch("posthog.tasks.alerts.trends.calculate_for_query_based_insight")
    def test_simulate_returns_valid_response(self, mock_calculate) -> None:
        mock_calculate.return_value = mock.MagicMock(
            result=[
                {
                    "data": [10.0, 12.0, 11.0, 50.0, 13.0, 12.0, 11.0] * 5,
                    "days": [f"2024-01-{i:02d}" for i in range(1, 36)],
                    "labels": [f"2024-01-{i:02d}" for i in range(1, 36)],
                    "label": "pageview",
                    "action": {"name": "pageview"},
                    "actions": [],
                    "count": 35,
                    "breakdown_value": "",
                    "status": None,
                    "compare_label": None,
                    "compare": False,
                    "persons_urls": [],
                    "persons": {},
                    "filter": {},
                }
            ]
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts/simulate",
            {
                "insight": self.insight["id"],
                "detector_config": {"type": "zscore", "threshold": 0.9, "window": 30},
                "series_index": 0,
            },
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        data = response.json()
        assert "data" in data
        assert "dates" in data
        assert "scores" in data
        assert "triggered_indices" in data
        assert "triggered_dates" in data
        assert "interval" in data
        assert "total_points" in data
        assert "anomaly_count" in data
        assert data["total_points"] == 35
        assert isinstance(data["scores"], list)
        assert len(data["scores"]) == 35

    def test_simulate_missing_detector_config_returns_400(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts/simulate",
            {
                "insight": self.insight["id"],
                "series_index": 0,
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_simulate_invalid_detector_config_returns_400(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts/simulate",
            {
                "insight": self.insight["id"],
                "detector_config": {"type": "nonexistent_detector"},
                "series_index": 0,
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @mock.patch("posthog.tasks.alerts.trends.calculate_for_query_based_insight")
    def test_simulate_does_not_create_alert_check_records(self, mock_calculate) -> None:
        mock_calculate.return_value = mock.MagicMock(
            result=[
                {
                    "data": [10.0, 12.0, 11.0, 50.0, 13.0, 12.0, 11.0] * 5,
                    "days": [f"2024-01-{i:02d}" for i in range(1, 36)],
                    "labels": [f"2024-01-{i:02d}" for i in range(1, 36)],
                    "label": "pageview",
                    "action": {"name": "pageview"},
                    "actions": [],
                    "count": 35,
                    "breakdown_value": "",
                    "status": None,
                    "compare_label": None,
                    "compare": False,
                    "persons_urls": [],
                    "persons": {},
                    "filter": {},
                }
            ]
        )

        checks_before = AlertCheck.objects.count()
        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts/simulate",
            {
                "insight": self.insight["id"],
                "detector_config": {"type": "zscore", "threshold": 0.9, "window": 30},
                "series_index": 0,
            },
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        assert AlertCheck.objects.count() == checks_before


class TestAlertAPIKeyAccess(APIBaseTest):
    """Test that the alert scope is properly enforced for API key access."""

    def setUp(self):
        super().setUp()
        self.insight = self.client.post(
            f"/api/projects/{self.team.id}/insights",
            data={
                "query": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    "trendsFilter": {"display": "BoldNumber"},
                },
            },
        ).json()
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight_id=self.insight["id"],
            name="Test Alert",
            created_by=self.user,
        )

    def _create_api_key(self, scopes: list[str]) -> str:
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=scopes,
        )
        return key_value

    @parameterized.expand(
        [
            (["feature_flag:read"], "get", "", status.HTTP_403_FORBIDDEN, "alert:read"),
            (["alert:read"], "get", "", status.HTTP_200_OK, None),
            (["alert:write"], "get", "", status.HTTP_200_OK, None),  # write grants read
            (["alert:read"], "get", "/{alert_id}/", status.HTTP_200_OK, None),
            (["alert:read"], "delete", "/{alert_id}/", status.HTTP_403_FORBIDDEN, "alert:write"),
            (["alert:write"], "delete", "/{alert_id}/", status.HTTP_204_NO_CONTENT, None),
        ]
    )
    def test_alert_api_key_access(self, scopes, http_method, endpoint_suffix, expected_status, error_scope):
        api_key = self._create_api_key(scopes)
        self.client.logout()

        endpoint = f"/api/projects/{self.team.id}/alerts{endpoint_suffix}".format(alert_id=self.alert.id)
        response = getattr(self.client, http_method)(endpoint, HTTP_AUTHORIZATION=f"Bearer {api_key}")

        assert response.status_code == expected_status
        if error_scope:
            assert error_scope in response.json()["detail"]

    @parameterized.expand(
        [
            (["insight:write"], status.HTTP_403_FORBIDDEN, "alert:write"),
            (["alert:read"], status.HTTP_403_FORBIDDEN, "alert:write"),
            (["alert:write"], status.HTTP_201_CREATED, None),
        ]
    )
    def test_alert_create_api_key_access(self, scopes, expected_status, error_scope):
        api_key = self._create_api_key(scopes)
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts/",
            data={
                "insight": self.insight["id"],
                "subscribed_users": [self.user.id],
                "name": "New Alert",
                "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            },
            HTTP_AUTHORIZATION=f"Bearer {api_key}",
        )

        assert response.status_code == expected_status
        if error_scope:
            assert error_scope in response.json()["detail"]
