from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.api.capture import CaptureInternalResult
from posthog.api.integration_push_tokens import MAX_SUBSCRIPTIONS_PER_REQUEST, _TokenCipher
from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team


def _capture_dropping(dropped_distinct_ids: set[str], warning_details: dict[str, str] | None = None):
    captured: list[dict[str, Any]] = []

    def capture(*, events: list[dict[str, Any]], **kwargs: Any) -> CaptureInternalResult:
        captured.append({"events": events, **kwargs})
        result = CaptureInternalResult(status_code=200)
        for event in events:
            if details := (warning_details or {}).get(event["distinct_id"]):
                result.warnings.append(event["event_uuid"])
                result.results[event["event_uuid"]] = {"result": "warning", "details": details}
                continue
            lane = result.dropped if event["distinct_id"] in dropped_distinct_ids else result.ok
            lane.append(event["event_uuid"])
        return result

    return capture, captured


class TestPushTokenImport(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.apns = Integration.objects.create(
            team=self.team,
            kind="apns",
            integration_id="TEAM.com.example.app",
            config={"bundle_id": "com.example.app", "team_id": "TEAM", "key_id": "KEY"},
        )
        self.firebase = Integration.objects.create(
            team=self.team,
            kind="firebase",
            integration_id="example-project",
            config={"project_id": "example-project"},
        )

    def _import(self, integration_id: int, subscriptions: list[dict[str, str]]):
        return self.client.post(
            f"/api/environments/{self.team.pk}/integrations/{integration_id}/push_tokens/",
            {"subscriptions": subscriptions},
            format="json",
        )

    @parameterized.expand([("apns", "com.example.app"), ("firebase", "example-project")])
    def test_stores_each_device_encrypted_under_the_key_the_sender_reads(self, kind: str, app_id: str) -> None:
        capture, captured = _capture_dropping(
            {"user-2"}, {"user-3": "person_processing_disabled", "user-4": "some_other_warning"}
        )
        with patch("posthog.api.integration_push_tokens.capture_batch_internal", side_effect=capture):
            response = self._import(
                getattr(self, kind).id,
                [
                    {"distinct_id": "user-1", "device_token": "a1b2c3d4"},
                    {"distinct_id": "user-1", "device_token": "a1b2c3d4"},
                    {"distinct_id": "user-1", "device_token": "second-device"},
                    {"distinct_id": "user-2", "device_token": "dropped-device"},
                    {"distinct_id": "user-3", "device_token": "skipped-device"},
                    {"distinct_id": "user-4", "device_token": "warned-device"},
                ],
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"imported": 3, "failed_distinct_ids": ["user-2", "user-3"]}
        [call] = captured
        assert call["token"] == self.team.api_token
        assert call["process_person_profile"] is True
        first = call["events"][0]
        assert first["event"] == "$set"
        assert first["distinct_id"] == "user-1"
        # The digest is what deviceSubscriptionKey in the Node sender computes for "a1b2c3d4".
        [(key, value)] = first["properties"]["$set"].items()
        assert key == f"$device_push_subscription_{app_id}:7dcf407fa84a0e05"
        assert value != "a1b2c3d4"
        assert _TokenCipher().decrypt(value) == "a1b2c3d4"
        assert len(call["events"]) == 5

    def test_rejects_an_integration_that_is_not_a_push_channel(self) -> None:
        slack = Integration.objects.create(team=self.team, kind="slack", integration_id="T1", config={})
        with patch("posthog.api.integration_push_tokens.capture_batch_internal") as capture:
            response = self._import(slack.id, [{"distinct_id": "user-1", "device_token": "a1b2c3d4"}])
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        capture.assert_not_called()

    def test_cannot_import_into_another_teams_channel(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="other"))
        other_apns = Integration.objects.create(
            team=other_team, kind="apns", integration_id="OTHER.app", config={"bundle_id": "com.other.app"}
        )
        with patch("posthog.api.integration_push_tokens.capture_batch_internal") as capture:
            response = self._import(other_apns.id, [{"distinct_id": "user-1", "device_token": "a1b2c3d4"}])
        assert response.status_code == status.HTTP_404_NOT_FOUND
        capture.assert_not_called()

    @parameterized.expand(
        [
            ("empty", []),
            ("too_many", [{"distinct_id": "u", "device_token": "t"}] * (MAX_SUBSCRIPTIONS_PER_REQUEST + 1)),
            ("missing_token", [{"distinct_id": "u"}]),
            ("blank_distinct_id", [{"distinct_id": "", "device_token": "t"}]),
        ]
    )
    def test_rejects_invalid_rows_without_capturing(self, _name: str, subscriptions: list[dict[str, str]]) -> None:
        with patch("posthog.api.integration_push_tokens.capture_batch_internal") as capture:
            response = self._import(self.apns.id, subscriptions)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        capture.assert_not_called()
