from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, QueryMatchingTest
from unittest import mock

from parameterized import parameterized
from rest_framework import status

from posthog.schema import AlertConditionType, AlertState, InsightThresholdType

from posthog.models import AlertConfiguration
from posthog.models.alert import AlertCheck
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value


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
            "schedule_restriction": None,
            "last_value": None,
            "investigation_agent_enabled": False,
            "investigation_gates_notifications": False,
            "investigation_inconclusive_action": "notify",
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

    @parameterized.expand(
        [
            ("default_limit", 8, "", 5),
            ("explicit_limit", 10, "?checks_limit=3", 3),
            ("capped_at_max", 3, "?checks_limit=9999", 3),
            ("negative_clamped_to_1", 5, "?checks_limit=-5", 1),
            ("zero_clamped_to_1", 5, "?checks_limit=0", 1),
            ("invalid_falls_back_to_default", 5, "?checks_limit=abc", 5),
        ]
    )
    def test_retrieve_checks_limit_behaviour(
        self, _name: str, total_checks: int, query_param: str, expected_count: int
    ) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "checks limit test",
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()
        alert_obj = AlertConfiguration.objects.get(id=alert["id"])

        for i in range(total_checks):
            AlertCheck.objects.create(
                alert_configuration=alert_obj,
                calculated_value=float(i),
                state=AlertState.NOT_FIRING,
            )

        response = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert['id']}{query_param}")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body["checks"]) == expected_count
        assert body["checks_total"] == total_checks

    @parameterized.expand(
        [
            ("returns_newest_slice_first", 3, 0, [7.0, 6.0, 5.0]),
            ("skips_newest_for_next_page", 3, 3, [4.0, 3.0, 2.0]),
            ("negative_offset_clamped_to_first_page", 2, -1, [7.0, 6.0]),
        ]
    )
    def test_retrieve_checks_offset_pagination(
        self, _label: str, checks_limit: int, checks_offset: int, expected_values: list[float]
    ) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "checks offset test",
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()
        alert_obj = AlertConfiguration.objects.get(id=alert["id"])

        now = datetime.now(UTC)
        for i in range(8):
            check = AlertCheck.objects.create(
                alert_configuration=alert_obj,
                calculated_value=float(i),
                state=AlertState.NOT_FIRING,
            )
            AlertCheck.objects.filter(id=check.id).update(created_at=now - timedelta(seconds=8 - i))

        response = self.client.get(
            f"/api/projects/{self.team.id}/alerts/{alert['id']}"
            f"?checks_limit={checks_limit}&checks_offset={checks_offset}"
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["checks_total"] == 8
        assert [c["calculated_value"] for c in body["checks"]] == expected_values

    def test_retrieve_checks_with_date_from(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "checks date test",
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()
        alert_obj = AlertConfiguration.objects.get(id=alert["id"])

        now = datetime.now(UTC)
        # Create 3 old checks (2 days ago) and 2 recent checks (now)
        for i in range(3):
            check = AlertCheck.objects.create(
                alert_configuration=alert_obj,
                calculated_value=float(i),
                state=AlertState.NOT_FIRING,
            )
            AlertCheck.objects.filter(id=check.id).update(created_at=now - timedelta(hours=48 + i))

        for i in range(2):
            AlertCheck.objects.create(
                alert_configuration=alert_obj,
                calculated_value=float(10 + i),
                state=AlertState.NOT_FIRING,
            )

        # Without date_from — returns last 5 (all of them)
        response = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert['id']}")
        assert len(response.json()["checks"]) == 5
        assert response.json()["checks_total"] == 5

        # With date_from=-24h — only the 2 recent checks
        response = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert['id']}?checks_date_from=-24h")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["checks_total"] == 2
        checks = response.json()["checks"]
        assert len(checks) == 2
        for check in checks:
            assert check["calculated_value"] >= 10.0

    def test_retrieve_checks_with_date_from_and_date_to(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "checks window test",
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()
        alert_obj = AlertConfiguration.objects.get(id=alert["id"])

        now = datetime.now(UTC)
        # Create checks at different times: 3 days ago, 2 days ago, 1 day ago, now
        times_and_values = [
            (now - timedelta(hours=72), 1.0),
            (now - timedelta(hours=48), 2.0),
            (now - timedelta(hours=24), 3.0),
            (now, 4.0),
        ]
        for created_at, value in times_and_values:
            check = AlertCheck.objects.create(
                alert_configuration=alert_obj,
                calculated_value=value,
                state=AlertState.NOT_FIRING,
            )
            AlertCheck.objects.filter(id=check.id).update(created_at=created_at)

        # Window from 4 days ago to 12 hours ago — should get checks with values 1.0, 2.0, 3.0 but not 4.0
        response = self.client.get(
            f"/api/projects/{self.team.id}/alerts/{alert['id']}?checks_date_from=-4d&checks_date_to=-12h"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["checks_total"] == 3
        checks = response.json()["checks"]
        assert len(checks) == 3
        values = [c["calculated_value"] for c in checks]
        assert 4.0 not in values

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

    @parameterized.expand(
        [
            (
                "null_interval_rejected",
                {"calculation_interval": None},
                status.HTTP_400_BAD_REQUEST,
                "weekly",
                None,
            ),
            (
                "omitted_interval_preserves_existing",
                {"name": "renamed alert"},
                status.HTTP_200_OK,
                "weekly",
                "renamed alert",
            ),
            (
                "updated_interval_applied",
                {"calculation_interval": "hourly"},
                status.HTTP_200_OK,
                "hourly",
                "alert name",
            ),
        ]
    )
    def test_patch_calculation_interval(self, _name, patch_payload, expected_status, expected_interval, expected_name):
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "alert name",
            "calculation_interval": "weekly",
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()
        assert alert["calculation_interval"] == "weekly"

        response = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{alert['id']}",
            patch_payload,
            content_type="application/json",
        )
        assert response.status_code == expected_status, response.content
        if expected_status == status.HTTP_200_OK:
            assert response.json()["calculation_interval"] == expected_interval
            assert response.json()["name"] == expected_name

    def test_create_alert_with_schedule_restriction(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "quiet alert",
            "schedule_restriction": {"blocked_windows": [{"start": "22:00", "end": "07:00"}]},
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)
        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert response.json()["schedule_restriction"] == {
            "blocked_windows": [{"start": "22:00", "end": "07:00"}],
        }

    def test_create_alert_rejects_schedule_restriction_covering_full_day(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "bad quiet",
            "schedule_restriction": {
                "blocked_windows": [
                    {"start": "00:00", "end": "12:00"},
                    {"start": "12:00", "end": "00:00"},
                ]
            },
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_patch_schedule_restriction_snaps_next_check_to_first_minute_outside_quiet_hours(self) -> None:
        """Changing quiet hours should persist a concrete next_check_at instead of null (avoids pointless enqueue cycles)."""
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "snap next",
            "calculation_interval": "hourly",
        }
        with freeze_time("2026-04-06T14:00:00Z"):
            alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request, format="json").json()
            AlertConfiguration.objects.filter(pk=alert["id"]).update(
                next_check_at=datetime(2026, 4, 6, 15, 30, tzinfo=UTC),
            )
            response = self.client.patch(
                f"/api/projects/{self.team.id}/alerts/{alert['id']}",
                {"schedule_restriction": {"blocked_windows": [{"start": "11:00", "end": "16:00"}]}},
                format="json",
            )
            assert response.status_code == status.HTTP_200_OK, response.content
            nxt = response.json()["next_check_at"]
            assert datetime.fromisoformat(nxt.replace("Z", "+00:00")) == datetime(2026, 4, 6, 16, 0, 0, tzinfo=UTC)

    def test_patch_schedule_restriction_empty_normalizes_to_null(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "alert",
            "schedule_restriction": {"blocked_windows": [{"start": "22:00", "end": "23:00"}]},
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()
        patch = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{alert['id']}",
            {"schedule_restriction": {"blocked_windows": []}},
            format="json",
        )
        assert patch.status_code == status.HTTP_200_OK, patch.content
        assert patch.json()["schedule_restriction"] is None

    def _line_graph_insight(self) -> dict[str, Any]:
        data = deepcopy(self.default_insight_data)
        data["query"]["trendsFilter"] = {"display": "ActionsLineGraph"}
        data["query"]["interval"] = "day"
        return self.client.post(f"/api/projects/{self.team.id}/insights", data=data).json()

    def _quiet_hours_alert_payload(self, insight_id: int, **extra: Any) -> dict[str, Any]:
        return {
            "insight": insight_id,
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "quiet hours alert",
            "schedule_restriction": {"blocked_windows": [{"start": "22:00", "end": "07:00"}]},
            **extra,
        }

    @parameterized.expand(
        [
            (
                "too_many_windows",
                {"blocked_windows": [{"start": f"{i:02d}:00", "end": f"{i:02d}:30"} for i in range(6)]},
            ),
            ("missing_start", {"blocked_windows": [{"end": "12:00"}]}),
            ("missing_end", {"blocked_windows": [{"start": "12:00"}]}),
            ("equal_start_end", {"blocked_windows": [{"start": "10:00", "end": "10:00"}]}),
            ("seconds_not_allowed", {"blocked_windows": [{"start": "12:00:00", "end": "13:00"}]}),
            ("invalid_hour", {"blocked_windows": [{"start": "25:00", "end": "26:00"}]}),
            ("non_object_window", {"blocked_windows": ["not-an-object"]}),
            ("blocked_windows_not_array", {"blocked_windows": {}}),
            ("window_shorter_than_30_min", {"blocked_windows": [{"start": "12:00", "end": "12:20"}]}),
        ]
    )
    def test_create_alert_rejects_invalid_schedule_restriction(
        self, _name: str, schedule_restriction: dict[str, Any]
    ) -> None:
        creation_request = self._quiet_hours_alert_payload(self.insight["id"])
        creation_request["schedule_restriction"] = schedule_restriction
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "invalid schedule restriction" in str(response.content).lower()

    @parameterized.expand(
        [
            ("utc", "UTC"),
            ("phoenix", "America/Phoenix"),
            ("tokyo", "Asia/Tokyo"),
        ]
    )
    def test_create_alert_schedule_restriction_with_team_timezone_wall_clock(
        self, _name: str, team_timezone: str
    ) -> None:
        # self.team is class-scoped test data; restore default so other tests are order-independent.
        try:
            self.team.timezone = team_timezone
            self.team.save(update_fields=["timezone"])
            creation_request = self._quiet_hours_alert_payload(self.insight["id"])
            response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request, format="json")
            assert response.status_code == status.HTTP_201_CREATED, response.content
            assert response.json()["schedule_restriction"] == {
                "blocked_windows": [{"start": "22:00", "end": "07:00"}],
            }
        finally:
            self.team.timezone = "UTC"
            self.team.save(update_fields=["timezone"])

    def test_create_alert_schedule_restriction_merges_overlapping_windows(self) -> None:
        creation_request = self._quiet_hours_alert_payload(self.insight["id"])
        creation_request["schedule_restriction"] = {
            "blocked_windows": [
                {"start": "10:30", "end": "11:00"},
                {"start": "10:40", "end": "11:15"},
            ]
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert response.json()["schedule_restriction"] == {
            "blocked_windows": [{"start": "10:30", "end": "11:15"}],
        }

    @parameterized.expand(
        [
            ("hourly", "hourly", True),
            ("daily", "daily", True),
            ("weekly", "weekly", False),
            ("monthly", "monthly", True),
        ]
    )
    def test_create_alert_quiet_hours_with_skip_weekend_and_calculation_interval(
        self, _name: str, interval: str, skip_weekend: bool
    ) -> None:
        creation_request = self._quiet_hours_alert_payload(
            self.insight["id"],
            calculation_interval=interval,
            skip_weekend=skip_weekend,
        )
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content
        data = response.json()
        assert data["calculation_interval"] == interval
        assert data["skip_weekend"] is skip_weekend
        assert data["schedule_restriction"] == {
            "blocked_windows": [{"start": "22:00", "end": "07:00"}],
        }

    def test_create_alert_quiet_hours_check_ongoing_skip_weekend_line_graph(self) -> None:
        line_insight = self._line_graph_insight()
        creation_request = {
            "insight": line_insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {
                "type": "TrendsAlertConfig",
                "series_index": 0,
                "check_ongoing_interval": True,
            },
            "threshold": {
                "configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}},
            },
            "name": "ongoing + quiet + weekend",
            "calculation_interval": "hourly",
            "skip_weekend": True,
            "schedule_restriction": {"blocked_windows": [{"start": "09:00", "end": "17:00"}]},
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content
        data = response.json()
        assert data["config"]["check_ongoing_interval"] is True
        assert data["skip_weekend"] is True
        assert data["calculation_interval"] == "hourly"
        assert data["schedule_restriction"] == {
            "blocked_windows": [{"start": "09:00", "end": "17:00"}],
        }

    def test_patch_alert_adds_quiet_hours_and_skip_weekend(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "name": "patch me",
            "calculation_interval": "daily",
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{alert['id']}",
            {
                "skip_weekend": True,
                "schedule_restriction": {"blocked_windows": [{"start": "12:00", "end": "13:00"}]},
                "calculation_interval": "weekly",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        data = response.json()
        assert data["skip_weekend"] is True
        assert data["calculation_interval"] == "weekly"
        assert data["schedule_restriction"] == {
            "blocked_windows": [{"start": "12:00", "end": "13:00"}],
        }

    def test_patch_alert_invalid_schedule_restriction_leaves_existing_unchanged(self) -> None:
        creation_request = self._quiet_hours_alert_payload(self.insight["id"])
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()
        bad = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{alert['id']}",
            {"schedule_restriction": {"blocked_windows": [{"start": "10:00", "end": "10:00"}]}},
            format="json",
        )
        assert bad.status_code == status.HTTP_400_BAD_REQUEST, bad.content
        refreshed = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert['id']}")
        assert refreshed.status_code == status.HTTP_200_OK
        assert refreshed.json()["schedule_restriction"] == {
            "blocked_windows": [{"start": "22:00", "end": "07:00"}],
        }


class TestInvestigationAgentValidation(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.insight_data: dict[str, Any] = {
            "query": {
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "event": "$pageview"}],
                "interval": "day",
            },
        }
        self.insight = self.client.post(f"/api/projects/{self.team.id}/insights", data=self.insight_data).json()

    def _base_alert_body(self, *, detector_config: dict[str, Any] | None, enabled: bool) -> dict[str, Any]:
        return {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "name": "investigation alert",
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "calculation_interval": "daily",
            "detector_config": detector_config,
            "investigation_agent_enabled": enabled,
        }

    @parameterized.expand(
        [
            ("enabled_without_detector_config", None, True, status.HTTP_400_BAD_REQUEST, "investigation_agent_enabled"),
            ("disabled_without_detector_config", None, False, status.HTTP_201_CREATED, None),
            (
                "enabled_with_detector_config",
                {"type": "zscore", "threshold": 0.95, "window": 30},
                True,
                status.HTTP_201_CREATED,
                None,
            ),
        ]
    )
    def test_investigation_agent_enabled_validation(
        self,
        _name: str,
        detector_config: dict[str, Any] | None,
        enabled: bool,
        expected_status: int,
        expected_error_attr: str | None,
    ) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            self._base_alert_body(detector_config=detector_config, enabled=enabled),
        )
        assert response.status_code == expected_status, response.content
        if expected_error_attr:
            assert expected_error_attr in response.json().get("attr", "")

    def test_investigation_gates_notifications_rejected_without_agent_enabled(self) -> None:
        body = self._base_alert_body(detector_config=None, enabled=False)
        body["investigation_gates_notifications"] = True
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", body)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "investigation_gates_notifications" in response.json().get("attr", "")


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

    @mock.patch("posthog.tasks.alerts.detector.calculate_for_query_based_insight")
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
        assert data["total_points"] == 34  # 35 mock points minus 1 dropped incomplete interval
        assert isinstance(data["scores"], list)
        assert len(data["scores"]) == 34

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

    @mock.patch("posthog.tasks.alerts.detector.calculate_for_query_based_insight")
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


class TestAlertEventProperties(APIBaseTest):
    @parameterized.expand(
        [
            (
                "threshold_absolute",
                {"type": "absolute_value"},
                None,
                {
                    "alert_mode": "threshold",
                    "detector_type": None,
                    "ensemble_operator": None,
                    "ensemble_detector_types": None,
                    "has_preprocessing": False,
                },
            ),
            (
                "single_detector_no_preprocessing",
                {"type": "absolute_value"},
                {"type": "zscore", "threshold": 0.95, "window": 30},
                {
                    "alert_mode": "detector",
                    "detector_type": "zscore",
                    "ensemble_operator": None,
                    "ensemble_detector_types": None,
                    "has_preprocessing": False,
                },
            ),
            (
                "single_detector_with_preprocessing",
                {"type": "absolute_value"},
                {"type": "zscore", "threshold": 0.95, "window": 30, "preprocessing": {"diffs_n": 1}},
                {
                    "alert_mode": "detector",
                    "detector_type": "zscore",
                    "ensemble_operator": None,
                    "ensemble_detector_types": None,
                    "has_preprocessing": True,
                },
            ),
            (
                "ensemble_and",
                {"type": "absolute_value"},
                {
                    "type": "ensemble",
                    "operator": "AND",
                    "detectors": [
                        {"type": "zscore", "threshold": 0.95, "window": 30, "preprocessing": {"diffs_n": 1}},
                        {"type": "mad", "threshold": 0.95, "window": 30},
                    ],
                },
                {
                    "alert_mode": "detector",
                    "detector_type": "ensemble",
                    "ensemble_operator": "AND",
                    "ensemble_detector_types": ["zscore", "mad"],
                    "has_preprocessing": True,
                },
            ),
            (
                "ensemble_or_no_preprocessing",
                {"type": "absolute_value"},
                {
                    "type": "ensemble",
                    "operator": "OR",
                    "detectors": [
                        {"type": "iqr", "multiplier": 1.5, "window": 30},
                        {"type": "threshold"},
                    ],
                },
                {
                    "alert_mode": "detector",
                    "detector_type": "ensemble",
                    "ensemble_operator": "OR",
                    "ensemble_detector_types": ["iqr", "threshold"],
                    "has_preprocessing": False,
                },
            ),
        ]
    )
    def test_event_properties(
        self,
        _name: str,
        condition: dict,
        detector_config: dict | None,
        expected_detector_fields: dict,
    ) -> None:
        alert = AlertConfiguration(
            name="test alert",
            condition=condition,
            detector_config=detector_config,
            calculation_interval="daily",
        )
        props = alert._get_event_properties()
        assert props["alert_name"] == "test alert"
        assert props["condition_type"] == condition["type"]
        assert props["calculation_interval"] == "daily"
        for key, value in expected_detector_fields.items():
            assert props[key] == value, f"{key} expected {value}, got {props[key]}"


class TestTriggerAlertHogFunctions(APIBaseTest):
    @parameterized.expand(
        [
            (
                "threshold_alert",
                None,
                {"alert_mode": "threshold", "detector_type": None, "ensemble_operator": None},
            ),
            (
                "single_detector",
                {"type": "zscore", "threshold": 0.95, "window": 30},
                {"alert_mode": "detector", "detector_type": "zscore", "ensemble_operator": None},
            ),
            (
                "ensemble_detector",
                {
                    "type": "ensemble",
                    "operator": "AND",
                    "detectors": [
                        {"type": "zscore", "threshold": 0.95, "window": 30},
                        {"type": "mad", "threshold": 0.95, "window": 30},
                    ],
                },
                {"alert_mode": "detector", "detector_type": "ensemble", "ensemble_operator": "AND"},
            ),
        ]
    )
    @mock.patch("posthog.tasks.alerts.utils.produce_internal_event")
    def test_insight_alert_firing_detector_props(
        self,
        _name: str,
        detector_config: dict | None,
        expected_props: dict,
        mock_produce: mock.MagicMock,
    ) -> None:
        from posthog.tasks.alerts.utils import trigger_alert_hog_functions

        alert = mock.MagicMock()
        alert.id = "00000000-0000-0000-0000-000000000001"
        alert.name = "test alert"
        alert.insight.name = "test insight"
        alert.insight.short_id = "abcd1234"
        alert.state = AlertState.FIRING
        alert.last_checked_at = None
        alert.team_id = self.team.id
        alert.detector_config = detector_config

        trigger_alert_hog_functions(alert, properties={"breaches": "test breach"})

        assert mock_produce.call_count == 1
        event = mock_produce.call_args.kwargs["event"]
        for key, value in expected_props.items():
            assert event.properties[key] == value, f"{key} expected {value}, got {event.properties[key]}"
        assert event.properties["breaches"] == "test breach"


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
