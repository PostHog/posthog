from datetime import datetime, timedelta
from typing import Optional

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.http import HttpResponse
from django.utils.timezone import now

import celery
import requests.exceptions
from boto3 import resource
from botocore.client import Config
from parameterized import parameterized
from rest_framework import status

from posthog.api.insight import InsightSerializer
from posthog.models import DashboardTile
from posthog.models.dashboard import Dashboard
from posthog.models.exported_asset import ExportedAsset
from posthog.models.filters.filter import Filter
from posthog.models.insight import Insight
from posthog.models.team import Team
from posthog.settings import (
    HOGQL_INCREASED_MAX_EXECUTION_TIME,
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)
from posthog.tasks import exporter
from posthog.tasks.exports.image_exporter import export_image

TEST_ROOT_BUCKET = "test_exports"


class TestExports(APIBaseTest):
    exported_asset: ExportedAsset
    dashboard: Dashboard
    insight: Insight
    tile: DashboardTile

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
        bucket.objects.filter(Prefix=TEST_ROOT_BUCKET).delete()

    insight_filter_dict = {
        "events": [{"id": "$pageview"}],
        "properties": [{"key": "$browser", "value": "Mac OS X"}],
    }

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.dashboard = Dashboard.objects.create(team=cls.team, name="example dashboard", created_by=cls.user)
        cls.insight = Insight.objects.create(
            filters=Filter(data=cls.insight_filter_dict).to_dict(),
            team=cls.team,
            created_by=cls.user,
            name="example insight",
        )
        cls.tile = DashboardTile.objects.create(dashboard=cls.dashboard, insight=cls.insight)
        cls.exported_asset = ExportedAsset.objects.create(
            team=cls.team, dashboard_id=cls.dashboard.id, export_format="image/png", created_by=cls.user
        )

    @patch("posthog.api.exports.exporter")
    def test_can_create_new_valid_export_dashboard(self, mock_exporter_task) -> None:
        # add filter to dashboard
        self.dashboard.filters = {"properties": [{"key": "$browser_version", "value": "1.0"}]}
        self.dashboard.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {"export_format": "image/png", "dashboard": self.dashboard.id},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        assert data == {
            "id": data["id"],
            "created_at": data["created_at"],
            "dashboard": self.dashboard.id,
            "exception": None,
            "export_format": "image/png",
            "filename": "export-example-dashboard.png",
            "has_content": False,
            "insight": None,
            "export_context": None,
            # without an expiry being set at creation, the default is 6 months
            "expires_after": (now() + timedelta(weeks=26))
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }

        mock_exporter_task.export_asset.assert_called_once_with(data["id"])

    @patch("posthog.api.exports.exporter")
    def test_can_create_export_with_ttl(self, mock_exporter_task) -> None:
        one_week_from_now = datetime.now() + timedelta(weeks=1)
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "image/png",
                "dashboard": self.dashboard.id,
                "expires_after": one_week_from_now.isoformat(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        assert data == {
            "id": data["id"],
            "created_at": data["created_at"],
            "dashboard": self.dashboard.id,
            "exception": None,
            "export_format": "image/png",
            "filename": "export-example-dashboard.png",
            "has_content": False,
            "insight": None,
            "export_context": None,
            "expires_after": one_week_from_now.isoformat() + "Z",
        }

        mock_exporter_task.export_asset.assert_called_once_with(data["id"])

    @patch("posthog.api.exports.exporter")
    def test_swallow_missing_schema_and_allow_front_end_to_poll(self, mock_exporter_task) -> None:
        # regression test see https://github.com/PostHog/posthog/issues/11204

        mock_exporter_task.get.side_effect = requests.exceptions.MissingSchema("why is this raised?")

        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "text/csv",
                "export_context": {
                    "path": f"api/projects/{self.team.id}/insights/trend/?insight=TRENDS&events=%5B%7B%22id%22%3A%22search%20filtered%22%2C%22name%22%3A%22search%20filtered%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%5D&actions=%5B%5D&display=ActionsTable&interval=day&breakdown=filters&new_entity=%5B%5D&properties=%5B%5D&breakdown_type=event&filter_test_accounts=false&date_from=-14d"
                },
            },
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            msg=f"was not HTTP 201 😱 - {response.json()}",
        )
        data = response.json()
        mock_exporter_task.export_asset.assert_called_once_with(data["id"])

    @patch("posthog.tasks.exports.image_exporter._export_to_png")
    @patch("posthog.api.exports.exporter")
    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_can_create_new_valid_export_insight(self, mock_exporter_task, mock_export_to_png) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {"export_format": "image/png", "insight": self.insight.id},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(
            data,
            {
                "id": data["id"],
                "created_at": data["created_at"],
                "insight": self.insight.id,
                "export_format": "image/png",
                "filename": "export-example-insight.png",
                "has_content": False,
                "dashboard": None,
                "exception": None,
                "export_context": None,
                "expires_after": (now() + timedelta(weeks=26))
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            },
        )

        self._assert_logs_the_activity(
            insight_id=self.insight.id,
            expected=[
                {
                    "user": {
                        "first_name": self.user.first_name,
                        "email": self.user.email,
                    },
                    "activity": "exported",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "Insight",
                    "item_id": str(self.insight.id),
                    "detail": {
                        "changes": [
                            {
                                "action": "exported",
                                "after": "image/png",
                                "before": None,
                                "field": "export_format",
                                "type": "Insight",
                            }
                        ],
                        "trigger": None,
                        "type": None,
                        "name": self.insight.name,
                        "short_id": self.insight.short_id,
                    },
                }
            ],
        )

        mock_exporter_task.export_asset.assert_called_once_with(data["id"])

        # look at the page the screenshot will be taken of
        exported_asset = ExportedAsset.objects.get(pk=data["id"])

        with patch("posthog.tasks.exports.image_exporter.process_query_dict") as mock_process_query_dict:
            # Request does not calculate the result and cache is not warmed up
            context = {"is_shared": True}
            InsightSerializer(self.insight, many=False, context=context)

            mock_process_query_dict.assert_not_called()

            # Should warm up the cache
            export_image(exported_asset)
            mock_export_to_png.assert_called_once_with(exported_asset)

            mock_process_query_dict.assert_called_once()

    def test_errors_if_missing_related_instance(self) -> None:
        response = self.client.post(f"/api/projects/{self.team.id}/exports", {"export_format": "image/png"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "attr": None,
                "code": "invalid_input",
                "detail": "Either dashboard, insight or export_context is required for an export.",
                "type": "validation_error",
            },
        )

    def test_errors_if_bad_format(self) -> None:
        response = self.client.post(f"/api/projects/{self.team.id}/exports", {"export_format": "not/allowed"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "attr": "export_format",
                "code": "invalid_choice",
                "detail": '"not/allowed" is not a valid choice.',
                "type": "validation_error",
            },
        )

    @patch("posthog.api.exports.exporter")
    def test_will_respond_even_if_task_timesout(self, mock_exporter_task) -> None:
        mock_exporter_task.export_asset.delay.return_value.get.side_effect = celery.exceptions.TimeoutError("timed out")
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {"export_format": "image/png", "insight": self.insight.id},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch("posthog.api.exports.exporter")
    def test_will_error_if_export_unsupported(self, mock_exporter_task) -> None:
        mock_exporter_task.export_asset.delay.return_value.get.side_effect = NotImplementedError("not implemented")
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {"export_format": "image/jpeg", "insight": self.insight.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "attr": "export_format",
                "code": "invalid_choice",
                "detail": '"image/jpeg" is not a valid choice.',
                "type": "validation_error",
            },
        )

    def test_will_error_if_dashboard_missing(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {"export_format": "application/pdf", "dashboard": 54321},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "attr": "dashboard",
                "code": "does_not_exist",
                "detail": 'Invalid pk "54321" - object does not exist.',
                "type": "validation_error",
            },
        )

    def test_will_error_if_export_contains_other_team_dashboard(self) -> None:
        other_team = Team.objects.create(
            organization=self.organization,
            api_token=self.CONFIG_API_TOKEN + "2",
            test_account_filters=[
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "not_icontains",
                    "type": "person",
                }
            ],
        )
        other_dashboard = Dashboard.objects.create(
            team=other_team, name="example dashboard other", created_by=self.user
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {"export_format": "application/pdf", "dashboard": other_dashboard.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "attr": "dashboard",
                "code": "invalid_input",
                "detail": "This dashboard does not belong to your team.",
                "type": "validation_error",
            },
        )

    def test_will_error_if_export_contains_other_team_insight(self) -> None:
        other_team = Team.objects.create(
            organization=self.organization,
            api_token=self.CONFIG_API_TOKEN + "2",
            test_account_filters=[
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "not_icontains",
                    "type": "person",
                }
            ],
        )
        other_insight = Insight.objects.create(
            filters=Filter(data=self.insight_filter_dict).to_dict(),
            team=other_team,
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {"export_format": "application/pdf", "insight": other_insight.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "attr": "insight",
                "code": "invalid_input",
                "detail": "This insight does not belong to your team.",
                "type": "validation_error",
            },
        )

    @patch("posthog.tasks.exports.csv_exporter.requests.request")
    def test_can_download_a_csv(self, patched_request) -> None:
        with self.settings(SITE_URL="http://testserver"):
            _create_event(
                event="event_name",
                team=self.team,
                distinct_id="2",
                properties={"$browser": "Chrome"},
            )
            expected_event_id = _create_event(
                event="event_name",
                team=self.team,
                distinct_id="2",
                properties={"$browser": "Safari"},
            )
            second_expected_event_id = _create_event(
                event="event_name",
                team=self.team,
                distinct_id="2",
                properties={"$browser": "Safari"},
            )
            third_expected_event_id = _create_event(
                event="event_name",
                team=self.team,
                distinct_id="2",
                properties={"$browser": "Safari"},
            )
            flush_persons_and_events()

            after = (datetime.now() - timedelta(minutes=10)).isoformat()

            def requests_side_effect(*args, **kwargs):
                response = self.client.get(kwargs["url"], kwargs["json"], **kwargs["headers"])

                def raise_for_status():
                    if 400 <= response.status_code < 600:
                        raise requests.exceptions.HTTPError(response=response)  # type: ignore[arg-type]

                response.raise_for_status = raise_for_status  # type: ignore[attr-defined]
                return response

            patched_request.side_effect = requests_side_effect

            response = self.client.post(
                f"/api/projects/{self.team.id}/exports",
                {
                    "export_format": "text/csv",
                    "export_context": {
                        "path": "&".join(
                            [
                                f"/api/projects/{self.team.id}/events?orderBy=%5B%22-timestamp%22%5D",
                                "properties=%5B%7B%22key%22%3A%22%24browser%22%2C%22value%22%3A%5B%22Safari%22%5D%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22event%22%7D%5D",
                                f"after={after}",
                            ]
                        )
                    },
                },
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_201_CREATED,
                msg=f"was not HTTP 201 😱 - {response.json()}",
            )
            instance = response.json()

            # limit the query to force it to page against the API
            with self.settings(OBJECT_STORAGE_ENABLED=False):
                exporter.export_asset(instance["id"], limit=1)

            download_response: Optional[HttpResponse] = None
            attempt_count = 0
            while attempt_count < 10 and not download_response:
                download_response = self.client.get(
                    f"/api/projects/{self.team.id}/exports/{instance['id']}/content?download=true"
                )
                attempt_count += 1

            if not download_response:
                self.fail("must have a response by this point")  # hi mypy

            self.assertEqual(download_response.status_code, status.HTTP_200_OK)
            self.assertIsNotNone(download_response.content)
            file_content = download_response.content.decode("utf-8")
            file_lines = file_content.split("\n")
            # has a header row and at least two other rows
            # don't care if the DB hasn't been reset before the test
            self.assertTrue(len(file_lines) > 3)
            self.assertIn(expected_event_id, file_content)
            self.assertIn(second_expected_event_id, file_content)
            self.assertIn(third_expected_event_id, file_content)
            for line in file_lines[1:]:  # every result has to match the filter though
                if line != "":  # skip the final empty line of the file
                    self.assertIn("Safari", line)

    def _get_insight_activity(self, insight_id: int, expected_status: int = status.HTTP_200_OK):
        url = f"/api/projects/{self.team.id}/insights/{insight_id}/activity"
        activity = self.client.get(url)
        self.assertEqual(activity.status_code, expected_status)
        return activity.json()

    def _assert_logs_the_activity(self, insight_id: int, expected: list[dict]) -> None:
        activity_response = self._get_insight_activity(insight_id)

        activity: list[dict] = activity_response["results"]

        self.maxDiff = None
        self.assertEqual(activity, expected)

    def test_can_list_exports(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/exports")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

        ExportedAsset.objects.create(
            team=self.team, dashboard_id=self.dashboard.id, export_format="image/png", created_by=self.user
        )

        # Also crete an unrelated export in the db
        ExportedAsset.objects.create(
            team=self.team, dashboard_id=self.dashboard.id, export_format="image/png", created_by=None
        )

        response = self.client.get(f"/api/projects/{self.team.id}/exports")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

    def test_list_shows_stuck_exports_as_failed_in_response(self) -> None:
        with freeze_time(now() - timedelta(seconds=2 * HOGQL_INCREASED_MAX_EXECUTION_TIME)):
            # Create an export that's older than HOGQL_INCREASED_MAX_EXECUTION_TIME
            stuck_export = ExportedAsset.objects.create(
                team=self.team,
                dashboard_id=self.dashboard.id,
                export_format="image/png",
                created_by=self.user,
                content=None,
                content_location=None,
                exception=None,
            )

            # Create an export that already has content - should not be marked as failed
            completed_export = ExportedAsset.objects.create(
                team=self.team,
                dashboard_id=self.dashboard.id,
                export_format="image/png",
                created_by=self.user,
                created_at=now() - timedelta(seconds=HOGQL_INCREASED_MAX_EXECUTION_TIME + 100),
                content=b"some content",
                exception=None,
            )

            # Create an export that has an exception - should not be overridden
            errored_export = ExportedAsset.objects.create(
                team=self.team,
                dashboard_id=self.dashboard.id,
                export_format="image/png",
                created_by=self.user,
                created_at=now() - timedelta(seconds=HOGQL_INCREASED_MAX_EXECUTION_TIME + 100),
                content=None,
                exception="exception",
            )

        # Create a recent export that should not be marked as failed
        recent_export = ExportedAsset.objects.create(
            team=self.team,
            dashboard_id=self.dashboard.id,
            export_format="image/png",
            created_by=self.user,
            content=None,
            content_location=None,
            exception=None,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/exports")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.json()["results"]
        results_by_id = {result["id"]: result for result in results}

        stuck_result = results_by_id[stuck_export.id]
        self.assertIsNotNone(stuck_result["exception"])
        self.assertIn(f"Export failed without throwing an exception", stuck_result["exception"])

        recent_result = results_by_id[recent_export.id]
        self.assertIsNone(recent_result["exception"])

        completed_result = results_by_id[completed_export.id]
        self.assertIsNone(completed_result["exception"])

        completed_result = results_by_id[errored_export.id]
        self.assertEqual("exception", completed_result["exception"])

        # Verify that the database wasn't actually modified
        stuck_export.refresh_from_db()
        recent_export.refresh_from_db()
        completed_export.refresh_from_db()
        self.assertIsNone(stuck_export.exception)
        self.assertIsNone(recent_export.exception)
        self.assertIsNone(completed_export.exception)

    def test_retrieve_shows_stuck_export_as_failed_in_response(self) -> None:
        with freeze_time(now() - timedelta(seconds=2 * HOGQL_INCREASED_MAX_EXECUTION_TIME)):
            # Create an export that's older than HOGQL_INCREASED_MAX_EXECUTION_TIME
            stuck_export = ExportedAsset.objects.create(
                team=self.team,
                dashboard_id=self.dashboard.id,
                export_format="image/png",
                created_by=self.user,
                created_at=now() - timedelta(seconds=HOGQL_INCREASED_MAX_EXECUTION_TIME + 100),
                content=None,
                content_location=None,
                exception=None,
            )

        response = self.client.get(f"/api/projects/{self.team.id}/exports/{stuck_export.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        result = response.json()

        # Check that the stuck export appears to have an exception in the response
        self.assertIsNotNone(result["exception"])
        self.assertIn(f"Export failed without throwing an exception", result["exception"])

        # Verify that the database wasn't actually modified
        stuck_export.refresh_from_db()
        self.assertIsNone(stuck_export.exception)

    @parameterized.expand(
        [
            ("image/png", 2, "png_export"),  # PNG format with 2 expected results
            ("text/csv", 1, "csv_export"),  # CSV format with 1 expected result
            ("image/jpeg", 3, None),  # Unsupported format returns all (3)
            (None, 3, None),  # No filter returns all (3)
        ]
    )
    def test_can_filter_exports_by_format(self, export_format, expected_count, expected_export_var):
        png_export = ExportedAsset.objects.create(
            team=self.team, dashboard_id=self.dashboard.id, export_format="image/png", created_by=self.user
        )
        csv_export = ExportedAsset.objects.create(
            team=self.team, insight_id=self.insight.id, export_format="text/csv", created_by=self.user
        )

        url = f"/api/projects/{self.team.id}/exports"
        if export_format:
            url += f"?export_format={export_format}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]

        assert len(results) == expected_count

        if expected_export_var == "png_export":
            # Should return PNG exports only (including the one from setUpTestData)
            png_export_ids = {png_export.id, self.exported_asset.id}
            returned_ids = {result["id"] for result in results}
            assert returned_ids == png_export_ids
            for result in results:
                assert result["export_format"] == "image/png"
        elif expected_export_var == "csv_export":
            # Should return CSV export only
            assert results[0]["id"] == csv_export.id
            assert results[0]["export_format"] == "text/csv"

    @patch("posthog.api.exports.async_to_sync")
    @patch("posthog.api.exports.async_connect")
    def test_video_export_monthly_limit(self, mock_async_connect, mock_async_to_sync) -> None:
        """Test that video exports are limited to 10 per calendar month"""
        # Create 9 video exports this month (we're at the limit - 1)
        for i in range(9):
            ExportedAsset.objects.create(
                team=self.team,
                export_format="video/mp4",
                export_context={"mode": "video", "session_recording_id": f"session_{i}"},
                created_by=self.user,
            )

        # The 10th video export should succeed
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "video/mp4",
                "export_context": {
                    "mode": "video",
                    "session_recording_id": "session_10",
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # The 11th video export should fail with limit exceeded error
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "video/mp4",
                "export_context": {
                    "mode": "video",
                    "session_recording_id": "session_11",
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error_data = response.json()
        self.assertEqual(error_data["type"], "validation_error")
        self.assertEqual(error_data["attr"], "export_limit_exceeded")
        self.assertIn("reached the limit of 10 full video exports this month", error_data["detail"])

    @patch("posthog.api.exports.async_to_sync")
    @patch("posthog.api.exports.async_connect")
    def test_video_export_limit_only_applies_to_full_videos(self, mock_async_connect, mock_async_to_sync) -> None:
        """Test that the limit only applies to full video exports (mode=video), not clips"""
        # Create 10 video exports this month (at the limit)
        for i in range(10):
            ExportedAsset.objects.create(
                team=self.team,
                export_format="video/mp4",
                export_context={"mode": "video", "session_recording_id": f"session_{i}"},
                created_by=self.user,
            )

        # Full video export should fail
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "video/mp4",
                "export_context": {
                    "mode": "video",
                    "session_recording_id": "session_full",
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # But clip export (screenshot mode) should succeed
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "video/mp4",
                "export_context": {
                    "mode": "screenshot",
                    "session_recording_id": "session_clip",
                    "timestamp": 100,
                    "duration": 5,
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Other video formats should also succeed
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "video/webm",
                "export_context": {
                    "mode": "video",
                    "session_recording_id": "session_webm",
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch("posthog.api.exports.async_to_sync")
    @patch("posthog.api.exports.async_connect")
    @freeze_time("2024-01-15T12:00:00Z")
    def test_video_export_limit_resets_monthly(self, mock_async_connect, mock_async_to_sync) -> None:
        """Test that the video export limit resets at the beginning of each month"""

        # Create 10 video exports in January (at the limit)
        for i in range(10):
            ExportedAsset.objects.create(
                team=self.team,
                export_format="video/mp4",
                export_context={"mode": "video", "session_recording_id": f"session_jan_{i}"},
                created_by=self.user,
            )

        # Should fail in January
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "video/mp4",
                "export_context": {
                    "mode": "video",
                    "session_recording_id": "session_jan_fail",
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Move to February 1st
        with freeze_time("2024-02-01T12:00:00Z"):
            # Should succeed in February (limit reset)
            response = self.client.post(
                f"/api/projects/{self.team.id}/exports",
                {
                    "export_format": "video/mp4",
                    "export_context": {
                        "mode": "video",
                        "session_recording_id": "session_feb_success",
                    },
                },
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class TestExportMixin(APIBaseTest):
    def _get_export_output(self, path: str) -> list[str]:
        """
        Use this function to test the CSV output of exports in other tests
        """
        with self.settings(SITE_URL="http://testserver", OBJECT_STORAGE_ENABLED=False):
            with patch("posthog.tasks.exports.csv_exporter.requests.request") as patched_request:

                def requests_side_effect(*args, **kwargs):
                    response = self.client.get(kwargs["url"], kwargs["json"], **kwargs["headers"])

                    def raise_for_status():
                        if 400 <= response.status_code < 600:
                            raise requests.exceptions.HTTPError(response=response)  # type: ignore[arg-type]

                    response.raise_for_status = raise_for_status  # type: ignore[attr-defined]
                    return response

                patched_request.side_effect = requests_side_effect

                response = self.client.post(
                    f"/api/projects/{self.team.pk}/exports/",
                    {
                        "export_context": {
                            "path": path,
                        },
                        "export_format": "text/csv",
                    },
                )
                download_response = self.client.get(
                    f"/api/projects/{self.team.id}/exports/{response.json()['id']}/content?download=true"
                )
                return [str(x) for x in download_response.content.splitlines()]
