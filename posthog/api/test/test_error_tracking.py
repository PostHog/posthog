import json
import os
from unittest.mock import ANY

from boto3 import resource
from botocore.config import Config
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils.http import urlsafe_base64_encode
from rest_framework import status

from posthog.models import Team, ErrorTrackingGroup
from posthog.settings import (
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    OBJECT_STORAGE_BUCKET,
)
from posthog.test.base import APIBaseTest

TEST_BUCKET = "test_storage_bucket-TestErrorTracking"


def get_path_to(fixture_file: str) -> str:
    file_dir = os.path.dirname(__file__)
    return os.path.join(file_dir, "fixtures", fixture_file)


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

    def test_can_upload_a_source_map(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER=TEST_BUCKET):
            with open(get_path_to("source.js.map"), "rb") as image:
                response = self.client.post(
                    f"/api/projects/{self.team.id}/error_tracking/upload_source_maps",
                    {"source_map": image},
                    format="multipart",
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())

    def test_rejects_too_large_file_type(self) -> None:
        fifty_megabytes_plus_a_little = b"1" * (50 * 1024 * 1024 + 1)
        fake_big_file = SimpleUploadedFile(
            name="large_source.js.map",
            content=fifty_megabytes_plus_a_little,
            content_type="text/plain",
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/error_tracking/upload_source_maps",
            {"source_map": fake_big_file},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertEqual(response.json()["detail"], "Source maps must be less than 50MB")

    def test_rejects_upload_when_object_storage_is_unavailable(self) -> None:
        with override_settings(OBJECT_STORAGE_ENABLED=False):
            fake_big_file = SimpleUploadedFile(name="large_source.js.map", content=b"", content_type="text/plain")
            response = self.client.post(
                f"/api/projects/{self.team.id}/error_tracking/upload_source_maps",
                {"source_map": fake_big_file},
                format="multipart",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
            self.assertEqual(
                response.json()["detail"],
                "Object storage must be available to allow source map uploads.",
            )

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
