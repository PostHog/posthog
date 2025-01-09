import os
import json
from boto3 import resource

from rest_framework import status

from django.utils.http import urlsafe_base64_encode

from django.test import override_settings
from django.core.files.uploadedfile import SimpleUploadedFile

from posthog.test.base import APIBaseTest
from posthog.models import (
    ErrorTrackingSymbolSet,
    ErrorTrackingStackFrame,
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingTeam,
)
from botocore.config import Config
from posthog.settings import (
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    OBJECT_STORAGE_BUCKET,
)

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

    # def test_reuses_existing_group_for_team(self):
    #     fingerprint = ["CustomFingerprint"]
    #     ErrorTrackingGroup.objects.create(fingerprint=fingerprint, team=self.team)

    #     self.assertEqual(ErrorTrackingGroup.objects.count(), 1)
    #     self.send_request(fingerprint, {"assignee": self.user.id})
    #     self.assertEqual(ErrorTrackingGroup.objects.count(), 1)

    # def test_creates_group_if_not_already_existing_for_team(self):
    #     fingerprint = ["CustomFingerprint"]
    #     other_team = Team.objects.create(organization=self.organization)
    #     ErrorTrackingGroup.objects.create(fingerprint=fingerprint, team=other_team)

    #     self.assertEqual(ErrorTrackingGroup.objects.count(), 1)
    #     self.send_request(fingerprint, {"assignee": self.user.id})
    #     self.assertEqual(ErrorTrackingGroup.objects.count(), 2)

    # def test_can_only_update_allowed_fields(self):
    #     fingerprint = ["CustomFingerprint"]
    #     other_team = Team.objects.create(organization=self.organization)
    #     group = ErrorTrackingGroup.objects.create(fingerprint=fingerprint, team=other_team)

    #     self.send_request(fingerprint, {"fingerprint": ["NewFingerprint"], "assignee": self.user.id})
    #     group.refresh_from_db()
    #     self.assertEqual(group.fingerprint, ["CustomFingerprint"])

    # def test_merging_of_an_existing_group(self):
    #     fingerprint = ["CustomFingerprint"]
    #     merging_fingerprints = [["NewFingerprint"]]
    #     group = ErrorTrackingGroup.objects.create(fingerprint=fingerprint, team=self.team)

    #     self.send_request(fingerprint, {"merging_fingerprints": merging_fingerprints}, endpoint="merge")

    #     group.refresh_from_db()
    #     self.assertEqual(group.merged_fingerprints, merging_fingerprints)

    # def test_merging_when_no_group_exists(self):
    #     fingerprint = ["CustomFingerprint"]
    #     merging_fingerprints = [["NewFingerprint"]]

    #     self.assertEqual(ErrorTrackingGroup.objects.count(), 0)
    #     self.send_request(fingerprint, {"merging_fingerprints": merging_fingerprints}, endpoint="merge")
    #     self.assertEqual(ErrorTrackingGroup.objects.count(), 1)
    #     groups = ErrorTrackingGroup.objects.only("merged_fingerprints")
    #     self.assertEqual(groups[0].merged_fingerprints, merging_fingerprints)

    def test_can_upload_a_source_map(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER=TEST_BUCKET):
            symbol_set = ErrorTrackingSymbolSet.objects.create(
                ref="https://app-static-prod.posthog.com/static/chunk-BPTF6YBO.js", team=self.team, storage_ptr=None
            )

            with open(get_path_to("source.js.map"), "rb") as image:
                # Note - we just use the source map twice, because we don't expect the API to do
                # any validation here - cymbal does the parsing work.
                # TODO - we could have the api validate these contents before uploading, if we wanted
                data = {"source_map": image, "minified": image}
                response = self.client.patch(
                    f"/api/projects/{self.team.id}/error_tracking/symbol_sets/{symbol_set.id}",
                    data,
                    format="multipart",
                )
                self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    # def test_rejects_too_large_file_type(self) -> None:
    #     symbol_set = ErrorTrackingSymbolSet.objects.create(
    #         ref="https://app-static-prod.posthog.com/static/chunk-BPTF6YBO.js", team=self.team, storage_ptr=None
    #     )
    #     fifty_megabytes_plus_a_little = b"1" * (1024 * 1024 * 1024 + 1)
    #     fake_big_file = SimpleUploadedFile(
    #         name="large_source.js.map",
    #         content=fifty_megabytes_plus_a_little,
    #         content_type="text/plain",
    #     )
    #     response = self.client.put(
    #         f"/api/projects/{self.team.id}/error_tracking/symbol_sets/{symbol_set.id}",
    #         {"source_map": fake_big_file},
    #         format="multipart",
    #     )
    #     self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
    #     self.assertEqual(response.json()["detail"], "Source maps must be less than 50MB")

    def test_rejects_upload_when_object_storage_is_unavailable(self) -> None:
        symbol_set = ErrorTrackingSymbolSet.objects.create(
            ref="https://app-static-prod.posthog.com/static/chunk-BPTF6YBO.js", team=self.team, storage_ptr=None
        )
        with override_settings(OBJECT_STORAGE_ENABLED=False):
            fake_big_file = SimpleUploadedFile(name="large_source.js.map", content=b"", content_type="text/plain")
            data = {"source_map": fake_big_file, "minified": fake_big_file}
            response = self.client.put(
                f"/api/projects/{self.team.id}/error_tracking/symbol_sets/{symbol_set.id}",
                data,
                format="multipart",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
            self.assertEqual(
                response.json()["detail"],
                "Object storage must be available to allow source map uploads.",
            )

    def test_fetching_symbol_sets(self):
        other_team = self.create_team_with_organization(organization=self.organization)
        ErrorTrackingSymbolSet.objects.create(ref="source_1", team=self.team, storage_ptr=None)
        ErrorTrackingSymbolSet.objects.create(
            ref="source_2", team=self.team, storage_ptr="https://app-static-prod.posthog.com/static/chunk-BPTF6YBO.js"
        )
        ErrorTrackingSymbolSet.objects.create(
            ref="source_2", team=other_team, storage_ptr="https://app-static-prod.posthog.com/static/chunk-BPTF6YBO.js"
        )

        self.assertEqual(ErrorTrackingSymbolSet.objects.count(), 3)

        # it only fetches symbol sets for the specified team
        response = self.client.get(f"/api/projects/{self.team.id}/error_tracking/symbol_sets")
        self.assertEqual(len(response.json()["results"]), 2)

    def test_fetching_stack_frames(self):
        other_team = self.create_team_with_organization(organization=self.organization)
        symbol_set = ErrorTrackingSymbolSet.objects.create(ref="source_1", team=self.team, storage_ptr=None)
        other_symbol_set = ErrorTrackingSymbolSet.objects.create(ref="source_2", team=self.team, storage_ptr=None)
        ErrorTrackingStackFrame.objects.create(
            raw_id="raw_id", team=self.team, symbol_set=symbol_set, resolved=True, contents={}
        )
        ErrorTrackingStackFrame.objects.create(
            raw_id="other_raw_id", team=self.team, symbol_set=other_symbol_set, resolved=True, contents={}
        )
        ErrorTrackingStackFrame.objects.create(
            raw_id="raw_id", team=other_team, symbol_set=symbol_set, resolved=True, contents={}
        )

        self.assertEqual(ErrorTrackingStackFrame.objects.count(), 3)

        # it only fetches stack traces for the specified team
        response = self.client.get(f"/api/projects/{self.team.id}/error_tracking/stack_frames")
        self.assertEqual(len(response.json()["results"]), 2)

        # fetching can be filtered by raw_ids
        response = self.client.get(f"/api/projects/{self.team.id}/error_tracking/stack_frames?raw_ids=raw_id")
        self.assertEqual(len(response.json()["results"]), 1)

        # fetching can be filtered by symbol set
        response = self.client.get(
            f"/api/projects/{self.team.id}/error_tracking/stack_frames?symbol_set={symbol_set.id}"
        )
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["symbol_set_ref"], symbol_set.ref)

    def test_assigning_issues(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        self.assertEqual(ErrorTrackingIssueAssignment.objects.count(), 0)
        self.client.patch(
            f"/api/projects/{self.team.id}/error_tracking/issue/{issue.id}/assign",
            data={"assignee": {"id": self.user.id, "type": "user"}},
        )
        # assigns the issue
        self.assertEqual(ErrorTrackingIssueAssignment.objects.count(), 1)
        self.assertEqual(ErrorTrackingIssueAssignment.objects.filter(issue=issue, user_id=self.user.id).count(), 1)

        self.client.patch(
            f"/api/projects/{self.team.id}/error_tracking/issue/{issue.id}/assign",
            data={"assignee": None},
        )
        # deletes the assignment
        self.assertEqual(ErrorTrackingIssueAssignment.objects.count(), 0)

        other_team = self.create_team_with_organization(organization=self.organization)
        response = self.client.patch(
            f"/api/projects/{other_team.id}/error_tracking/issue/{issue.id}/assign",
            data={"assignee": None},
        )
        # cannot assign issues from other teams
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_error_tracking_teams(self):
        self.client.post(
            f"/api/projects/{self.team.id}/error_tracking/teams",
            data={"name": "My team"},
        )

        # creates the team
        error_tracking_team = ErrorTrackingTeam.objects.get(team=self.team)
        self.assertIsNotNone(error_tracking_team)
        self.assertEqual(error_tracking_team.name, "My team")

        self.client.post(
            f"/api/projects/{self.team.id}/error_tracking/teams/{error_tracking_team.id}/add",
            data={"userId": self.user.id},
        )
        # adds a team member
        self.assertEqual(error_tracking_team.members.count(), 1)

        self.client.post(
            f"/api/projects/{self.team.id}/error_tracking/teams/{error_tracking_team.id}/remove",
            data={"userId": self.user.id},
        )
        # removes a team member
        self.assertEqual(error_tracking_team.members.count(), 0)
