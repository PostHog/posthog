from unittest.mock import ANY

from rest_framework import status

from posthog.test.base import APIBaseTest
from posthog.models import Team, ErrorTrackingGroup
from django.utils.http import urlsafe_base64_encode
import json


class TestErrorTracking(APIBaseTest):
    def send_request(self, fingerprint, data, endpoint=""):
        base64_fingerprint = urlsafe_base64_encode(json.dumps(fingerprint).encode("utf-8"))
        request_method = self.client.patch if endpoint == "" else self.client.post
        request_method(
            f"/api/projects/{self.team.id}/error_tracking/{base64_fingerprint}/{endpoint}",
            data=data,
        )

    def test_reuses_existing_group_for_team(self):
        fingerprint = ["CustomFingerprint"]
        ErrorTrackingGroup.objects.create(fingerprint=fingerprint, team=self.team)

        self.assertEqual(ErrorTrackingGroup.objects.count(), 1)
        self.send_request(fingerprint, {"assignee": self.user.id})
        self.assertEqual(ErrorTrackingGroup.objects.count(), 1)

    def test_creates_group_if_not_already_existing_for_team(self):
        fingerprint = ["CustomFingerprint"]
        other_team = Team.objects.create(organization=self.organization)
        ErrorTrackingGroup.objects.create(fingerprint=fingerprint, team=other_team)

        self.assertEqual(ErrorTrackingGroup.objects.count(), 1)
        self.send_request(fingerprint, {"assignee": self.user.id})
        self.assertEqual(ErrorTrackingGroup.objects.count(), 2)

    def test_can_only_update_allowed_fields(self):
        fingerprint = ["CustomFingerprint"]
        other_team = Team.objects.create(organization=self.organization)
        group = ErrorTrackingGroup.objects.create(fingerprint=fingerprint, team=other_team)

        self.send_request(fingerprint, {"fingerprint": ["NewFingerprint"], "assignee": self.user.id})
        group.refresh_from_db()
        self.assertEqual(group.fingerprint, ["CustomFingerprint"])

    def test_merging_of_an_existing_group(self):
        fingerprint = ["CustomFingerprint"]
        merging_fingerprints = [["NewFingerprint"]]
        group = ErrorTrackingGroup.objects.create(fingerprint=fingerprint, team=self.team)

        self.send_request(fingerprint, {"merging_fingerprints": merging_fingerprints}, endpoint="merge")

        group.refresh_from_db()

        self.assertEqual(group.merged_fingerprints, merging_fingerprints)

        self._assert_logs_the_activity(
            group.id,
            [
                {
                    "activity": "merged_fingerprints",
                    "created_at": ANY,
                    "detail": {
                        "changes": [
                            {
                                "action": "merged",
                                "after": [["NewFingerprint"]],
                                "before": [],
                                "field": "merged_fingerprints",
                                "type": "ErrorTrackingGroup",
                            }
                        ],
                        "name": None,
                        "short_id": None,
                        "trigger": None,
                        "type": None,
                    },
                    "item_id": str(group.id),
                    "scope": "ErrorTrackingGroup",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                }
            ],
        )

    def test_merging_when_no_group_exists(self):
        fingerprint = ["CustomFingerprint"]
        merging_fingerprints = [["NewFingerprint"]]

        self.assertEqual(ErrorTrackingGroup.objects.count(), 0)
        self.send_request(fingerprint, {"merging_fingerprints": merging_fingerprints}, endpoint="merge")
        self.assertEqual(ErrorTrackingGroup.objects.count(), 1)
        groups = ErrorTrackingGroup.objects.only("merged_fingerprints")
        self.assertEqual(groups[0].merged_fingerprints, merging_fingerprints)

    def _assert_logs_the_activity(self, error_tracking_group_id: int, expected: list[dict]) -> None:
        activity_response = self._get_error_group_activity(error_tracking_group_id)

        activity: list[dict] = activity_response["results"]

        self.maxDiff = None
        self.assertEqual(activity, expected)

    def _get_error_group_activity(
        self, error_tracking_group_id: int, expected_status: int = status.HTTP_200_OK
    ) -> dict:
        url = f"/api/projects/{self.team.id}/error_tracking/{error_tracking_group_id}/activity"
        activity = self.client.get(url)
        self.assertEqual(activity.status_code, expected_status)
        return activity.json()
