from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, QueryMatchingTest
from unittest import mock

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.schema import AlertCalculationInterval, AlertConditionType, AlertState, InsightThresholdType

from posthog.api.tagged_item import set_tags_on_object
from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.alerts.backend.destinations import AlertDelivery
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, AlertSubscription, Threshold
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.product_analytics.backend.facade.models import Insight

TEST_DESTINATION_DELIVERY = AlertDelivery(
    channel="hog_function", target="Eng alerts", template="slack", at="2026-08-11T00:00:00+00:00"
)


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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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
            "insight_display_name": mock.ANY,
            "insight_short_id": mock.ANY,
            "last_notified_at": None,
            "name": "alert name",
            "subscribed_users": mock.ANY,
            "state": "Not firing",
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "detector_config": None,
            "threshold": {
                "configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}},
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

    def test_alert_rejects_insight_without_viewer_access(self) -> None:
        # Alert write access must not let a user reference an insight they can't view — otherwise
        # they could exfiltrate a restricted insight's results via notifications / check history.
        def deny_insight(obj=None, *args, **kwargs) -> bool:
            return type(obj).__name__ != "Insight"

        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "name": "alert name",
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
            "calculation_interval": "daily",
        }
        # An alert created while access is allowed, so we can test the insight-swap update vector.
        alert_id = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()["id"]

        with mock.patch(
            "products.access_control.backend.facade.user_access_control.UserAccessControl.check_access_level_for_object",
            side_effect=deny_insight,
        ):
            create = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)
            update = self.client.patch(
                f"/api/projects/{self.team.id}/alerts/{alert_id}", {"insight": self.insight["id"]}
            )
            simulate = self.client.post(
                f"/api/projects/{self.team.id}/alerts/simulate/",
                {"insight": self.insight["id"], "detector_config": {"type": "zscore", "threshold": 0.9}},
            )

        for response in (create, update, simulate):
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
            assert "access to this insight" in str(response.json())

    def test_existing_alert_hidden_when_insight_viewer_access_is_lost(self) -> None:
        # An existing alert must not outlive viewer access to its linked insight: otherwise its
        # check history (breaching rows / values) leaks on read, and a PATCH that omits `insight`
        # bypasses the create-time check. The queryset gate hides it from list, retrieve, update, and delete.
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "name": "alert name",
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
            "calculation_interval": "daily",
        }
        alert_id = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()["id"]

        # Deny viewer access to every insight by emptying the viewable-insight queryset.
        with mock.patch(
            "products.access_control.backend.facade.user_access_control.UserAccessControl.filter_queryset_by_access_level",
            side_effect=lambda queryset, *args, **kwargs: queryset.none(),
        ):
            retrieve = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert_id}")
            listed = self.client.get(f"/api/projects/{self.team.id}/alerts")
            update = self.client.patch(f"/api/projects/{self.team.id}/alerts/{alert_id}", {"name": "renamed"})
            delete = self.client.delete(f"/api/projects/{self.team.id}/alerts/{alert_id}")

        assert retrieve.status_code == status.HTTP_404_NOT_FOUND, retrieve.content
        assert update.status_code == status.HTTP_404_NOT_FOUND, update.content
        assert delete.status_code == status.HTTP_404_NOT_FOUND, delete.content
        assert [a["id"] for a in listed.json()["results"]] == []

    def test_create_alert_on_funnel_insight(self) -> None:
        funnel_insight = self.client.post(
            f"/api/projects/{self.team.id}/insights",
            data={
                "query": {
                    "kind": "FunnelsQuery",
                    "series": [
                        {"kind": "EventsNode", "event": "$pageview"},
                        {"kind": "EventsNode", "event": "$autocapture"},
                    ],
                }
            },
        ).json()
        creation_request = {
            "insight": funnel_insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "FunnelsAlertConfig", "metric": "conversion_from_start", "funnel_step": None},
            "name": "funnel alert",
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 50}}},
            "calculation_interval": "daily",
        }

        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)
        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_create_threshold_alert_rejects_empty_bounds(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "name": "alert name",
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}},
            "calculation_interval": "daily",
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "At least one threshold bound" in str(response.json())

    @parameterized.expand(
        [
            ("alert_name", "a" * 256, ""),
            ("threshold_name", "alert name", "a" * 256),
        ]
    )
    def test_create_alert_rejects_over_long_name(self, _name: str, alert_name: str, threshold_name: str) -> None:
        # Over-long names used to sail past validation and 500 on the Postgres write
        # (value too long for varchar(255)); the serializer must reject them with a 400.
        creation_request: dict[str, Any] = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "name": alert_name,
            "threshold": {
                "name": threshold_name,
                "configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}},
            },
            "calculation_interval": "daily",
        }

        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content

    def test_patch_alert_rejects_over_long_name(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "name": "alert name",
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
            "calculation_interval": "daily",
        }
        alert_id = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()["id"]
        response = self.client.patch(f"/api/projects/{self.team.id}/alerts/{alert_id}", {"name": "a" * 256})
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content

    def test_patch_legacy_empty_bounds_alert_without_touching_threshold(self) -> None:
        threshold = Threshold.objects.create(
            team=self.team,
            insight_id=self.insight["id"],
            configuration={"type": InsightThresholdType.ABSOLUTE, "bounds": {}},
        )
        alert = AlertConfiguration.objects.create(
            team=self.team,
            insight_id=self.insight["id"],
            name="legacy no-op",
            condition={"type": AlertConditionType.ABSOLUTE_VALUE},
            config={"type": "TrendsAlertConfig", "series_index": 0},
            threshold=threshold,
            calculation_interval=AlertCalculationInterval.DAILY,
            enabled=True,
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{alert.id}",
            {"enabled": False},
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        alert.refresh_from_db()
        assert alert.enabled is False

    def test_patch_empty_threshold_bounds_rejected(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "name": "alert name",
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
            "calculation_interval": "daily",
        }
        alert_id = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()["id"]
        response = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{alert_id}",
            {"threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {}}}},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "At least one threshold bound" in str(response.json())

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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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

    @parameterized.expand(
        [
            (
                "recorded_email_composed_as_accepted",
                {"users": ["a@example.com"], "destinations": []},
                [
                    {
                        "channel": "email",
                        "target": "a@example.com",
                        "status": "accepted",
                        "at": "2026-08-11T00:00:00+00:00",
                        "display_label": "Email: a@example.com",
                    }
                ],
                True,
            ),
            (
                "row_predating_receipts_is_null_but_still_notified",
                {"users": ["a@example.com"]},
                None,
                True,
            ),
            (
                "hog_function_only_delivery_keeps_truthful_yes",
                {
                    "users": [],
                    "destinations": [
                        {
                            "channel": "hog_function",
                            "target": "Slack #eng-alerts",
                            "target_id": "hf-1",
                            "template": "slack",
                            "status": "accepted",
                            "at": "2026-08-11T00:00:00+00:00",
                        }
                    ],
                },
                [
                    {
                        "channel": "hog_function",
                        "target": "Slack #eng-alerts",
                        "target_id": "hf-1",
                        "template": "slack",
                        "status": "accepted",
                        "at": "2026-08-11T00:00:00+00:00",
                        "display_label": "Slack #eng-alerts",
                    }
                ],
                True,
            ),
            (
                "combined_email_and_destination_row",
                {
                    "users": ["a@example.com"],
                    "destinations": [
                        {
                            "channel": "hog_function",
                            "target": "Slack #eng-alerts",
                            "target_id": "hf-1",
                            "template": "slack",
                            "status": "accepted",
                            "at": "2026-08-11T00:00:00+00:00",
                        }
                    ],
                },
                [
                    {
                        "channel": "email",
                        "target": "a@example.com",
                        "status": "accepted",
                        "at": "2026-08-11T00:00:00+00:00",
                        "display_label": "Email: a@example.com",
                    },
                    {
                        "channel": "hog_function",
                        "target": "Slack #eng-alerts",
                        "target_id": "hf-1",
                        "template": "slack",
                        "status": "accepted",
                        "at": "2026-08-11T00:00:00+00:00",
                        "display_label": "Slack #eng-alerts",
                    },
                ],
                True,
            ),
            (
                "non_slack_destinations_carry_an_id_suffix",
                {
                    "users": [],
                    "destinations": [
                        {
                            "channel": "hog_function",
                            "target": "Discord",
                            "target_id": "hf-aaaa4f2a",
                            "template": "discord",
                            "status": "accepted",
                            "at": "2026-08-11T00:00:00+00:00",
                        },
                        {
                            "channel": "hog_function",
                            "target": "Webhook example.com",
                            "target_id": "hf-bbbb9b17",
                            "template": "webhook",
                            "status": "accepted",
                            "at": "2026-08-11T00:00:00+00:00",
                        },
                        {
                            "channel": "hog_function",
                            "target": "Slack #eng-alerts",
                            "target_id": "hf-cccc0000",
                            "template": "slack",
                            "status": "accepted",
                            "at": "2026-08-11T00:00:00+00:00",
                        },
                    ],
                },
                [
                    {
                        "channel": "hog_function",
                        "target": "Discord",
                        "target_id": "hf-aaaa4f2a",
                        "template": "discord",
                        "status": "accepted",
                        "at": "2026-08-11T00:00:00+00:00",
                        "display_label": "Discord · 4f2a",
                    },
                    {
                        "channel": "hog_function",
                        "target": "Webhook example.com",
                        "target_id": "hf-bbbb9b17",
                        "template": "webhook",
                        "status": "accepted",
                        "at": "2026-08-11T00:00:00+00:00",
                        "display_label": "Webhook example.com · 9b17",
                    },
                    {
                        "channel": "hog_function",
                        "target": "Slack #eng-alerts",
                        "target_id": "hf-cccc0000",
                        "template": "slack",
                        "status": "accepted",
                        "at": "2026-08-11T00:00:00+00:00",
                        "display_label": "Slack #eng-alerts",
                    },
                ],
                True,
            ),
            (
                "nothing_recorded_is_null",
                {},
                None,
                False,
            ),
        ]
    )
    def test_alert_check_deliveries_field(
        self,
        _name: str,
        targets_notified: dict,
        expected_deliveries: list[dict] | None,
        expected_targets_notified: bool,
    ) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
            "name": "deliveries field test",
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()
        check = AlertCheck.objects.create(
            alert_configuration_id=alert["id"],
            targets_notified=targets_notified,
            notification_sent_at=datetime(2026, 8, 11, 0, 0, tzinfo=UTC) if targets_notified else None,
            state=AlertState.FIRING,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert['id']}")
        serialized = next(c for c in response.json()["checks"] if c["id"] == str(check.id))
        assert serialized["deliveries"] == expected_deliveries
        assert serialized["targets_notified"] is expected_targets_notified

    def test_alert_limit(self) -> None:
        with mock.patch(
            "products.alerts.backend.presentation.views.alert.AlertConfiguration.ALERTS_ALLOWED_ON_FREE_TIER"
        ) as alert_limit:
            alert_limit.__get__ = mock.Mock(return_value=1)

            creation_request = {
                "insight": self.insight["id"],
                "subscribed_users": [
                    self.user.id,
                ],
                "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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
        insight_without_alert_support["query"] = {"kind": "RetentionQuery", "retentionFilter": {}}
        self.client.patch(
            f"/api/projects/{self.team.id}/insights/{another_insight['id']}",
            data=insight_without_alert_support,
        ).json()

        response = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert['id']}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_hogql_alert_survives_insight_update_and_is_listed_on_insight(self) -> None:
        hogql_insight_data: dict[str, Any] = {
            "query": {
                "kind": "DataVisualizationNode",
                "source": {"kind": "HogQLQuery", "query": "select count() from events"},
            },
        }
        hogql_insight = self.client.post(f"/api/projects/{self.team.id}/insights", data=hogql_insight_data).json()

        alert = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            {
                "insight": hogql_insight["id"],
                "subscribed_users": [self.user.id],
                "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
                "config": {"type": "HogQLAlertConfig", "evaluation": "last_row"},
                "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
                "name": "sql alert",
            },
        ).json()

        # The insight response must list the alert inline — the UI trusts this list on reload.
        insight_response = self.client.get(f"/api/projects/{self.team.id}/insights/{hogql_insight['id']}").json()
        assert [a["id"] for a in insight_response["alerts"]] == [alert["id"]]

        # Updating the insight while it stays SQL-backed must not cascade-delete the alert.
        updated = deepcopy(hogql_insight_data)
        updated["query"]["source"]["query"] = "select count() + 1 from events"
        self.client.patch(f"/api/projects/{self.team.id}/insights/{hogql_insight['id']}", data=updated)
        response = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert['id']}")
        assert response.status_code == status.HTTP_200_OK

        # Changing to a kind that cannot carry alerts still cascades.
        self.client.patch(
            f"/api/projects/{self.team.id}/insights/{hogql_insight['id']}",
            data={"query": {"kind": "RetentionQuery", "retentionFilter": {}}},
        )
        response = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert['id']}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_funnel_alert_survives_insight_update_and_is_listed_on_insight(self) -> None:
        funnel_insight_data: dict[str, Any] = {
            "query": {
                "kind": "FunnelsQuery",
                "series": [
                    {"kind": "EventsNode", "event": "$pageview"},
                    {"kind": "EventsNode", "event": "$autocapture"},
                ],
            },
        }
        funnel_insight = self.client.post(f"/api/projects/{self.team.id}/insights", data=funnel_insight_data).json()

        alert = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            {
                "insight": funnel_insight["id"],
                "subscribed_users": [self.user.id],
                "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
                "config": {"type": "FunnelsAlertConfig", "metric": "conversion_from_start", "funnel_step": None},
                "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 50}}},
                "name": "funnel alert",
            },
        ).json()

        # The insight response must list the alert inline — the UI trusts this list on reload.
        insight_response = self.client.get(f"/api/projects/{self.team.id}/insights/{funnel_insight['id']}").json()
        assert [a["id"] for a in insight_response["alerts"]] == [alert["id"]]

        # Updating the insight while it stays funnel-backed must not cascade-delete the alert.
        updated = deepcopy(funnel_insight_data)
        updated["query"]["series"][1]["event"] = "$pageleave"
        self.client.patch(f"/api/projects/{self.team.id}/insights/{funnel_insight['id']}", data=updated)
        response = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert['id']}")
        assert response.status_code == status.HTTP_200_OK

        # Changing to a kind that cannot carry alerts still cascades.
        self.client.patch(
            f"/api/projects/{self.team.id}/insights/{funnel_insight['id']}",
            data={"query": {"kind": "RetentionQuery", "retentionFilter": {}}},
        )
        response = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert['id']}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_alert_survives_switch_between_alertable_kinds(self) -> None:
        # Switching the insight to a different alertable kind (trends -> SQL) leaves the alert's config
        # mismatched, but the alert is NOT deleted: the check cycle re-validates against the current
        # query and auto-disables + notifies on mismatch (covered by the validation/auto-disable tests),
        # so the alert and its history survive the edit and the user can reconfigure it.
        trends_insight = self.client.post(
            f"/api/projects/{self.team.id}/insights", data=self.default_insight_data
        ).json()
        alert_id = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            {
                "insight": trends_insight["id"],
                "subscribed_users": [self.user.id],
                "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
                "name": "trends alert",
            },
        ).json()["id"]

        # Switch the insight from trends to SQL — a different alertable kind.
        self.client.patch(
            f"/api/projects/{self.team.id}/insights/{trends_insight['id']}",
            data={
                "query": {
                    "kind": "DataVisualizationNode",
                    "source": {"kind": "HogQLQuery", "query": "select count() from events"},
                }
            },
        )
        assert self.client.get(f"/api/projects/{self.team.id}/alerts/{alert_id}").status_code == status.HTTP_200_OK

    def test_alert_is_deleted_on_insight_soft_delete(self) -> None:
        another_insight = self.client.post(
            f"/api/projects/{self.team.id}/insights", data=self.default_insight_data
        ).json()
        creation_request = {
            "insight": another_insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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

        patch_response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{another_insight['id']}",
            data={"deleted": True},
        )
        assert patch_response.status_code == status.HTTP_200_OK

        response = self.client.get(f"/api/projects/{self.team.id}/alerts/{alert_id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

        linked_hog_function.refresh_from_db()
        assert linked_hog_function.deleted is True
        assert linked_hog_function.enabled is False

    def test_delete_alert_cleans_up_hog_functions(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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

        self.client.patch(f"/api/projects/{self.team.id}/alerts/{firing_alert.id}", {"enabled": False})
        disabled_and_snoozed_alert = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{firing_alert.id}",
            {"snoozed_until": datetime.now()},
        ).json()
        assert disabled_and_snoozed_alert["enabled"] is False
        assert disabled_and_snoozed_alert["state"] == AlertState.NOT_FIRING
        disabled_check = AlertCheck.objects.filter(alert_configuration=firing_alert.id).latest("created_at")
        assert disabled_check.state == AlertState.NOT_FIRING

        enabled_and_snoozed_alert = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{firing_alert.id}",
            {"enabled": True, "snoozed_until": "1d"},
        ).json()
        assert enabled_and_snoozed_alert["enabled"] is True
        assert enabled_and_snoozed_alert["state"] == AlertState.SNOOZED

        snoozed_alert = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{firing_alert.id}",
            {"snoozed_until": datetime.now()},
        ).json()
        assert snoozed_alert["state"] == AlertState.SNOOZED

        edited_snoozed_alert = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{firing_alert.id}",
            {"threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 200}}}},
        ).json()
        assert edited_snoozed_alert["state"] == AlertState.NOT_FIRING

        edited_and_snoozed_alert = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{firing_alert.id}",
            {
                "snoozed_until": "1d",
                "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 300}}},
            },
        ).json()
        assert edited_and_snoozed_alert["state"] == AlertState.SNOOZED

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
                "detector_on_non_time_series",
                {
                    "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
                    "config": {"type": "TrendsAlertConfig", "series_index": 0},
                    "detector_config": {"type": "zscore", "threshold": 0.95, "window": 30},
                },
                "anomaly detection isn't supported for non time series trends",
            ),
            (
                "absolute_with_percentage_threshold",
                {
                    "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
                    "config": {"type": "TrendsAlertConfig", "series_index": 0},
                    "threshold": {"configuration": {"type": InsightThresholdType.PERCENTAGE, "bounds": {"upper": 100}}},
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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
            "name": "alert name",
            **overrides,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert expected_error_fragment in response.json()["detail"].lower()

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
                    "threshold": {"configuration": {"type": InsightThresholdType.PERCENTAGE, "bounds": {"upper": 100}}},
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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
            "name": "alert name",
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()
        assert "id" in alert, alert

        response = self.client.patch(f"/api/projects/{self.team.id}/alerts/{alert['id']}", overrides)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert expected_error_fragment in str(response.content).lower()

    def test_patch_alert_rejects_detector_for_non_time_series(self) -> None:
        pie_insight_data = deepcopy(self.default_insight_data)
        pie_insight_data["query"]["trendsFilter"]["display"] = "ActionsPie"
        pie_insight = self.client.post(f"/api/projects/{self.team.id}/insights", data=pie_insight_data).json()

        alert = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            {
                "insight": pie_insight["id"],
                "subscribed_users": [self.user.id],
                "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
                "name": "alert name",
            },
        ).json()
        assert "id" in alert, alert

        response = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{alert['id']}",
            {"detector_config": {"type": "zscore", "threshold": 0.95, "window": 30}},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "anomaly detection isn't supported for non time series trends" in response.json()["detail"].lower()

    @parameterized.expand(
        [
            (
                "null_interval_rejected",
                {"calculation_interval": None},
                status.HTTP_400_BAD_REQUEST,
                "weekly",
                None,
                False,
            ),
            (
                "omitted_interval_preserves_existing",
                {"name": "renamed alert"},
                status.HTTP_200_OK,
                "weekly",
                "renamed alert",
                False,
            ),
            (
                "updated_interval_applied",
                {"calculation_interval": "hourly"},
                status.HTTP_200_OK,
                "hourly",
                "alert name",
                True,
            ),
        ]
    )
    def test_patch_calculation_interval(
        self,
        _name: str,
        patch_payload: dict[str, Any],
        expected_status: int,
        expected_interval: str,
        expected_name: str | None,
        clears_next_check: bool,
    ) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
            "name": "alert name",
            "calculation_interval": "weekly",
        }
        alert = self.client.post(f"/api/projects/{self.team.id}/alerts", creation_request).json()
        assert alert["calculation_interval"] == "weekly"
        scheduled_check = datetime(2027, 1, 1, tzinfo=UTC)
        AlertConfiguration.objects.filter(id=alert["id"]).update(next_check_at=scheduled_check)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{alert['id']}",
            patch_payload,
            content_type="application/json",
        )
        assert response.status_code == expected_status, response.content
        if expected_status == status.HTTP_200_OK:
            assert response.json()["calculation_interval"] == expected_interval
            assert response.json()["name"] == expected_name

        persisted_alert = AlertConfiguration.objects.get(id=alert["id"])
        assert persisted_alert.next_check_at == (None if clears_next_check else scheduled_check)

    def test_create_alert_with_schedule_restriction(self) -> None:
        creation_request = {
            "insight": self.insight["id"],
            "subscribed_users": [self.user.id],
            "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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
            "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
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

    @mock.patch("products.alerts.backend.evaluation.detector.calculate_for_query_based_insight")
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

    @mock.patch("products.alerts.backend.evaluation.detector.calculate_for_query_based_insight")
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


class TestAlertTestDelivery(APIBaseTest):
    def setUp(self):
        super().setUp()
        insight = self.client.post(
            f"/api/projects/{self.team.id}/insights",
            data={
                "query": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    "trendsFilter": {"display": "BoldNumber"},
                }
            },
        ).json()
        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "insight": insight["id"],
                "name": "Testable alert",
                "subscribed_users": [],
                "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        self.alert = response.json()

    def _create_destination(self, *, enabled: bool = True, alert_id: str | None = None) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name="Alert destination",
            type="internal_destination",
            template_id="template-webhook",
            enabled=enabled,
            inputs_schema=[],
            inputs={},
            hog="return event",
            filters={
                "events": [{"id": "$insight_alert_firing", "type": "events"}],
                "properties": [
                    {
                        "key": "alert_id",
                        "value": alert_id or self.alert["id"],
                        "operator": "exact",
                        "type": "event",
                    }
                ],
            },
        )

    @mock.patch("products.alerts.backend.presentation.views.alert.trigger_alert_hog_functions")
    def test_queues_test_delivery_for_active_destinations_without_changing_alert(self, mock_trigger) -> None:
        mock_trigger.return_value = [TEST_DESTINATION_DELIVERY]
        self._create_destination()
        self._create_destination()
        self._create_destination(enabled=False)
        self._create_destination(alert_id="00000000-0000-0000-0000-000000000000")
        alert_before = AlertConfiguration.objects.get(id=self.alert["id"])

        response = self.client.post(f"/api/projects/{self.team.id}/alerts/{self.alert['id']}/test-delivery/")

        assert response.status_code == status.HTTP_202_ACCEPTED, response.content
        assert response.json() == {
            "destination_count": 2,
            "email_recipient_count": 0,
            "failed_delivery_channels": [],
        }
        mock_trigger.assert_called_once_with(
            mock.ANY,
            {
                "breaches": "Test alert from PostHog. No action is needed.",
                "is_test": True,
                "alert_name": "[TEST] Testable alert",
            },
        )
        alert_after = AlertConfiguration.objects.get(id=self.alert["id"])
        assert alert_after.state == alert_before.state
        assert alert_after.last_notified_at == alert_before.last_notified_at
        assert AlertCheck.objects.filter(alert_configuration_id=self.alert["id"]).count() == 0

    @mock.patch("products.alerts.backend.presentation.views.alert.trigger_alert_hog_functions")
    @mock.patch("products.alerts.backend.email_notifications.EmailMessage")
    def test_sends_test_delivery_to_subscribed_users_without_a_destination(
        self, mock_email_message, mock_trigger
    ) -> None:
        alert = AlertConfiguration.objects.get(id=self.alert["id"])
        AlertSubscription.objects.create(alert_configuration=alert, user=self.user)

        response = self.client.post(f"/api/projects/{self.team.id}/alerts/{self.alert['id']}/test-delivery/")

        assert response.status_code == status.HTTP_202_ACCEPTED, response.content
        assert response.json() == {
            "destination_count": 0,
            "email_recipient_count": 1,
            "failed_delivery_channels": [],
        }
        mock_email_message.assert_called_once()
        assert mock_email_message.call_args.kwargs["subject"] == "Test alert: Testable alert for Default project"
        mock_email_message.return_value.add_recipient.assert_called_once_with(email=self.user.email)
        mock_email_message.return_value.send.assert_called_once_with()
        mock_trigger.assert_not_called()

    @mock.patch(
        "products.alerts.backend.presentation.views.alert.send_test_alert_email",
        side_effect=RuntimeError("email failed"),
    )
    @mock.patch(
        "products.alerts.backend.presentation.views.alert.trigger_alert_hog_functions",
        return_value=[TEST_DESTINATION_DELIVERY],
    )
    def test_destination_still_queues_when_email_fails(self, mock_trigger, _mock_email) -> None:
        alert = AlertConfiguration.objects.get(id=self.alert["id"])
        AlertSubscription.objects.create(alert_configuration=alert, user=self.user)
        self._create_destination()

        response = self.client.post(f"/api/projects/{self.team.id}/alerts/{self.alert['id']}/test-delivery/")

        assert response.status_code == status.HTTP_202_ACCEPTED, response.content
        assert response.json() == {
            "destination_count": 1,
            "email_recipient_count": 0,
            "failed_delivery_channels": ["email"],
        }
        mock_trigger.assert_called_once()

    @mock.patch("products.alerts.backend.presentation.views.alert.trigger_alert_hog_functions", return_value=[])
    def test_returns_service_unavailable_when_destination_fails_to_queue(self, mock_trigger) -> None:
        self._create_destination()

        response = self.client.post(f"/api/projects/{self.team.id}/alerts/{self.alert['id']}/test-delivery/")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, response.content
        assert response.json() == {
            "detail": "Unable to start the test delivery. Check the configured channels and try again."
        }
        mock_trigger.assert_called_once()

    @mock.patch("products.alerts.backend.presentation.views.alert.trigger_alert_hog_functions")
    def test_rejects_test_delivery_without_active_destinations(self, mock_trigger) -> None:
        self._create_destination(enabled=False)

        response = self.client.post(f"/api/projects/{self.team.id}/alerts/{self.alert['id']}/test-delivery/")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json() == {"detail": "Add an email recipient or active destination before sending a test."}
        mock_trigger.assert_not_called()

    @mock.patch("posthog.rate_limit.AlertTestDeliveryThrottle.rate", new="2/minute")
    @mock.patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @mock.patch("products.alerts.backend.presentation.views.alert.trigger_alert_hog_functions")
    def test_rate_limits_test_delivery_per_team(self, _mock_trigger, _rate_limit_enabled) -> None:
        cache.clear()
        self._create_destination()
        endpoint = f"/api/projects/{self.team.id}/alerts/{self.alert['id']}/test-delivery/"

        assert self.client.post(endpoint).status_code == status.HTTP_202_ACCEPTED
        assert self.client.post(endpoint).status_code == status.HTTP_202_ACCEPTED
        assert self.client.post(endpoint).status_code == status.HTTP_429_TOO_MANY_REQUESTS
        cache.clear()


class TestAlertEventProperties(APIBaseTest):
    @parameterized.expand(
        [
            (
                "threshold_absolute",
                {"type": "absolute_value"},
                None,
                "daily",
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
                "daily",
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
                "daily",
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
                "daily",
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
                "daily",
                {
                    "alert_mode": "detector",
                    "detector_type": "ensemble",
                    "ensemble_operator": "OR",
                    "ensemble_detector_types": ["iqr", "threshold"],
                    "has_preprocessing": False,
                },
            ),
            (
                "every_15_minutes_high_frequency",
                {"type": "absolute_value"},
                None,
                "every_15_minutes",
                {
                    "alert_mode": "threshold",
                    "detector_type": None,
                    "ensemble_operator": None,
                    "ensemble_detector_types": None,
                    "has_preprocessing": False,
                    "is_high_frequency_interval": True,
                },
            ),
        ]
    )
    def test_event_properties(
        self,
        _name: str,
        condition: dict,
        detector_config: dict | None,
        calculation_interval: str,
        expected_detector_fields: dict,
    ) -> None:
        alert = AlertConfiguration(
            name="test alert",
            condition=condition,
            detector_config=detector_config,
            calculation_interval=calculation_interval,
        )
        props = alert._get_event_properties()
        assert props["alert_name"] == "test alert"
        assert props["condition_type"] == condition["type"]
        assert props["calculation_interval"] == calculation_interval
        assert props["is_high_frequency_interval"] == (
            calculation_interval == AlertCalculationInterval.EVERY_15_MINUTES
        )
        for key, value in expected_detector_fields.items():
            assert props[key] == value, f"{key} expected {value}, got {props[key]}"

    @parameterized.expand(
        [
            (
                "trends_config",
                {"type": "TrendsAlertConfig", "series_index": 1},
                {
                    "config_type": "TrendsAlertConfig",
                    "trends_series_index": 1,
                    "hogql_evaluation": None,
                    "hogql_has_explicit_column": None,
                    "hogql_has_label_column": None,
                },
            ),
            (
                "hogql_default",
                {"type": "HogQLAlertConfig", "evaluation": "last_row"},
                {
                    "config_type": "HogQLAlertConfig",
                    "hogql_evaluation": "last_row",
                    "hogql_has_explicit_column": False,
                    "hogql_has_label_column": False,
                },
            ),
            (
                "hogql_any_row_with_columns",
                {"type": "HogQLAlertConfig", "evaluation": "any_row", "column": "errors", "label_column": "country"},
                {
                    "config_type": "HogQLAlertConfig",
                    "hogql_evaluation": "any_row",
                    "hogql_has_explicit_column": True,
                    "hogql_has_label_column": True,
                },
            ),
        ]
    )
    def test_event_properties_capture_alert_config_adoption(self, _name: str, config: dict, expected: dict) -> None:
        alert = AlertConfiguration(
            name="test alert",
            condition={"type": "absolute_value"},
            config=config,
            calculation_interval="daily",
        )
        props = alert._get_event_properties()
        for key, value in expected.items():
            assert props[key] == value, f"{key} expected {value}, got {props[key]}"


class TestAlertListFilters(APIBaseTest):
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

    def _create_alert(
        self,
        name: str,
        user: User | None = None,
        *,
        insight_id: int | None = None,
        detector_config: dict[str, Any] | None = None,
    ) -> AlertConfiguration:
        return AlertConfiguration.objects.create(
            team=self.team,
            insight_id=insight_id if insight_id is not None else self.insight["id"],
            name=name,
            created_by=user or self.user,
            detector_config=detector_config,
        )

    def test_list_filter_by_insight_tag_and_detector_type(self) -> None:
        tagged_insight = Insight.objects.get(id=self.insight["id"])
        set_tags_on_object(["ai-observability"], tagged_insight)
        untagged_insight = self.client.post(
            f"/api/projects/{self.team.id}/insights", data=self.default_insight_data
        ).json()

        matching_alert = self._create_alert(
            "Tagged anomaly alert",
            detector_config={"type": "zscore", "threshold": 0.9, "window": 30},
        )
        threshold_alert = self._create_alert("Tagged threshold alert")
        untagged_alert = self._create_alert(
            "Untagged anomaly alert",
            insight_id=untagged_insight["id"],
            detector_config={"type": "zscore", "threshold": 0.9, "window": 30},
        )

        unfiltered_response = self.client.get(f"/api/projects/{self.team.id}/alerts")
        assert {alert["id"] for alert in unfiltered_response.json()["results"]} == {
            str(matching_alert.id),
            str(threshold_alert.id),
            str(untagged_alert.id),
        }

        response = self.client.get(
            f"/api/projects/{self.team.id}/alerts",
            {"insight_tag": "AI-Observability", "has_detector": "true"},
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert [alert["id"] for alert in results] == [str(matching_alert.id)]
        assert results[0]["insight_short_id"] == tagged_insight.short_id
        assert results[0]["insight_display_name"] == "Untitled insight"

    def test_list_filter_by_search(self) -> None:
        self._create_alert("Revenue spike")
        self._create_alert("Unrelated alert")

        response = self.client.get(f"/api/projects/{self.team.id}/alerts", {"search": "Reven"})
        result_names = [alert["name"] for alert in response.json()["results"]]

        assert result_names == ["Revenue spike"]

    def test_list_filter_by_created_by_uuid(self) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", None)

        self._create_alert("Mine", user=self.user)
        self._create_alert("Theirs", user=other_user)

        response = self.client.get(
            f"/api/projects/{self.team.id}/alerts",
            {"created_by": str(other_user.uuid)},
        )
        result_names = [alert["name"] for alert in response.json()["results"]]

        assert result_names == ["Theirs"]

    def test_list_filter_by_search_and_created_by(self) -> None:
        other_user = User.objects.create_and_join(self.organization, "other2@posthog.com", None)

        self._create_alert("Revenue spike", user=self.user)
        self._create_alert("Revenue other", user=other_user)
        self._create_alert("Unrelated", user=other_user)

        response = self.client.get(
            f"/api/projects/{self.team.id}/alerts",
            {"search": "Revenue", "created_by": str(other_user.uuid)},
        )
        result_names = [alert["name"] for alert in response.json()["results"]]

        assert result_names == ["Revenue other"]

    @parameterized.expand(
        [
            ("email in name", "alerts+ops@example.com", "alerts+ops@example.com"),
            ("uuid in name", "run 1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed", "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed"),
            ("dotted identifier", "com.acme.billing alert", "com.acme.billing"),
        ]
    )
    def test_list_filter_by_search_matches_literal_substring_below_trigram_threshold(
        self, _name: str, alert_name: str, search: str
    ) -> None:
        self._create_alert(alert_name)
        self._create_alert("Totally unrelated")

        response = self.client.get(f"/api/projects/{self.team.id}/alerts", {"search": search})
        results = response.json()["results"]

        match_type_by_name = {a["name"]: a["search_match_type"] for a in results}
        assert match_type_by_name.get(alert_name) == "exact", (
            "a literal substring must match and be labelled exact even when it scores below the trigram thresholds"
        )
        assert all(a["name"] != "Totally unrelated" for a in results)

    def test_list_filter_by_search_hides_similar_matches_when_exact_matches_exist(self) -> None:
        for name in ("revenue spike", "spike in revenue", "reveneu drop", "Unrelated alert"):
            self._create_alert(name)

        response = self.client.get(f"/api/projects/{self.team.id}/alerts", {"search": "revenue"})
        results = response.json()["results"]

        match_type_by_name = {a["name"]: a["search_match_type"] for a in results}
        assert match_type_by_name == {
            "revenue spike": "exact",
            "spike in revenue": "exact",
        }, "similar matches must be hidden when exact matches exist"

    def test_list_filter_by_search_match_type_absent_without_search(self) -> None:
        self._create_alert("Revenue spike")

        response = self.client.get(f"/api/projects/{self.team.id}/alerts")
        results = response.json()["results"]

        assert results
        assert all("search_match_type" not in a for a in results)

    @parameterized.expand(
        [
            ("search_length_cap", {"search": "a" * 201}, "search"),
            ("invalid_created_by_uuid", {"created_by": "not-a-uuid"}, "created_by"),
            ("invalid_has_detector", {"has_detector": "sometimes"}, "has_detector"),
        ]
    )
    def test_list_filter_validation_errors(self, _name: str, query_params: dict[str, str], expected_attr: str) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/alerts", query_params)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == expected_attr


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
            (
                ["alert:read"],
                "post",
                "/{alert_id}/test-delivery/",
                status.HTTP_403_FORBIDDEN,
                "alert:write",
            ),
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
                "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 100}}},
            },
            HTTP_AUTHORIZATION=f"Bearer {api_key}",
        )

        assert response.status_code == expected_status
        if error_scope:
            assert error_scope in response.json()["detail"]

    @parameterized.expand(
        [
            # simulate returns an insight's result series, so alert:read alone isn't enough.
            (["feature_flag:read"], "alert:read"),
            (["alert:read"], "insight:read"),
        ]
    )
    def test_simulate_requires_insight_read_scope(self, scopes, missing_scope):
        api_key = self._create_api_key(scopes)
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts/simulate/",
            data={"insight": self.insight["id"], "detector_config": {"type": "zscore", "threshold": 0.9}},
            HTTP_AUTHORIZATION=f"Bearer {api_key}",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert missing_scope in response.json()["detail"]

    @parameterized.expand(
        [
            (["alert:read", "insight:read"],),
            (["alert:write", "insight:write"],),  # write grants read for both
        ]
    )
    @mock.patch("products.alerts.backend.evaluation.detector.calculate_for_query_based_insight")
    def test_simulate_with_both_scopes_passes_the_gate(self, scopes, mock_calculate) -> None:
        mock_calculate.return_value = mock.MagicMock(
            result=[
                {
                    "data": [10.0, 12.0, 11.0, 50.0, 13.0, 12.0, 11.0] * 5,
                    "days": [f"2024-01-{i:02d}" for i in range(1, 36)],
                    "labels": [f"2024-01-{i:02d}" for i in range(1, 36)],
                    "label": "pageview",
                }
            ]
        )
        api_key = self._create_api_key(scopes)
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts/simulate/",
            data={
                "insight": self.insight["id"],
                "detector_config": {"type": "zscore", "threshold": 0.9, "window": 30},
                "series_index": 0,
            },
            HTTP_AUTHORIZATION=f"Bearer {api_key}",
        )

        assert response.status_code == status.HTTP_200_OK, response.content


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

    def test_patch_real_time_succeeds_with_entitlement(self) -> None:
        self._enable_real_time_alerts()
        create_response = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request())
        alert_id = create_response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{alert_id}",
            {"name": "updated real time alert"},
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["name"] == "updated real time alert"
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

    def test_real_time_limit_ignores_disabled_alerts(self) -> None:
        self._enable_real_time_alerts(limit=1)
        first = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request())
        assert first.status_code == status.HTTP_201_CREATED, first.content

        self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{first.json()['id']}",
            {"enabled": False},
        )

        second = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request(name="second"))
        assert second.status_code == status.HTTP_201_CREATED, second.content

    def test_real_time_limit_ignores_other_intervals(self) -> None:
        self._enable_real_time_alerts(limit=1)
        daily = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            self._creation_request(name="daily", calculation_interval=AlertCalculationInterval.DAILY),
        )
        assert daily.status_code == status.HTTP_201_CREATED, daily.content

        response = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request())
        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_patch_to_real_time_rejected_when_limit_reached(self) -> None:
        self._enable_real_time_alerts(limit=1)
        real_time = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request())
        assert real_time.status_code == status.HTTP_201_CREATED, real_time.content

        daily = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            self._creation_request(name="daily", calculation_interval=AlertCalculationInterval.DAILY),
        )
        assert daily.status_code == status.HTTP_201_CREATED, daily.content

        response = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{daily.json()['id']}",
            {"calculation_interval": AlertCalculationInterval.REAL_TIME},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "limit of 1 real-time alerts" in str(response.json())

    def test_enable_real_time_rejected_when_limit_reached(self) -> None:
        self._enable_real_time_alerts(limit=1)
        first = self.client.post(f"/api/projects/{self.team.id}/alerts", self._creation_request())
        assert first.status_code == status.HTTP_201_CREATED, first.content

        disabled = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            self._creation_request(name="disabled", enabled=False),
        )
        assert disabled.status_code == status.HTTP_201_CREATED, disabled.content

        response = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{disabled.json()['id']}",
            {"enabled": True},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "limit of 1 real-time alerts" in str(response.json())
