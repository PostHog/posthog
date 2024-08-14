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

    def test_merging_when_no_group_exists(self):
        fingerprint = ["CustomFingerprint"]
        merging_fingerprints = [["NewFingerprint"]]

        self.assertEqual(ErrorTrackingGroup.objects.count(), 0)
        self.send_request(fingerprint, {"merging_fingerprints": merging_fingerprints}, endpoint="merge")
        self.assertEqual(ErrorTrackingGroup.objects.count(), 1)
        groups = ErrorTrackingGroup.objects.only("merged_fingerprints")
        self.assertEqual(groups[0].merged_fingerprints, merging_fingerprints)
