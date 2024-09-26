from posthog.test.base import APIBaseTest
from posthog.models import Team, ErrorTrackingGroup
from django.utils.http import urlsafe_base64_encode
from boto3 import resource
from botocore.config import Config
from posthog.settings import (
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    OBJECT_STORAGE_BUCKET,
)
from unittest.mock import patch, MagicMock
import json

TEST_BUCKET = "test_storage_bucket-TestErrorTracking"


class TestErrorTracking(APIBaseTest):
    def teardown_method(self, method) -> None:
        s3 = resource(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
        bucket.objects.filter(Prefix=TEST_BUCKET).delete()

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

    @patch("posthog.api.error_tracking.object_storage.write")
    def test_uploading_sourcemaps(self, mock_write: MagicMock):
        with self.settings(OBJECT_STORAGE_ERROR_TRACKING_SOURCEMAPS_FOLDER=TEST_BUCKET):
            self.client.post(
                f"/api/projects/{self.team.id}/error_tracking/upload_sourcemap",
                data={"url": "https://app-static.eu.posthog.com/static/chunk-TWIAGSRT.js.map"},
            )

            mock_write.assert_called_with(
                f"{TEST_BUCKET}/team-{self.team.pk}/d41d8cd98f00b204e9800998ecf8427e",
                "This is the content I want to upload",
            )
