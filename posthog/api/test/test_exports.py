from contextlib import nullcontext
from datetime import datetime, timedelta
from typing import Optional

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events
from unittest.mock import ANY, AsyncMock, patch

from django.http import HttpResponse
from django.utils.timezone import now

import requests.exceptions
from boto3 import resource
from botocore.client import Config
from parameterized import parameterized
from prometheus_client import CollectorRegistry, Counter
from rest_framework import status

from posthog.hogql.errors import QueryError

from posthog.api.insight import InsightSerializer
from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.models.exported_asset import ExportedAsset
from posthog.models.filters.filter import Filter
from posthog.models.insight import Insight
from posthog.models.team import Team
from posthog.models.user import User
from posthog.settings import (
    HOGQL_INCREASED_MAX_EXECUTION_TIME,
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)
from posthog.tasks import exporter
from posthog.tasks.exports.failure_handler import FAILURE_TYPE_SYSTEM, FAILURE_TYPE_USER
from posthog.tasks.exports.image_exporter import export_image

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile

from ee.models.rbac.access_control import AccessControl

TEST_ROOT_BUCKET = "test_exports"


def get_counter_value(counter: Counter, labels: dict) -> float:
    """Get counter value using the _metrics dict directly (works across threads)."""
    label_values = tuple(str(labels.get(label, "")) for label in counter._labelnames)
    metric = counter._metrics.get(label_values)
    if metric is None:
        return 0.0
    value_container = getattr(metric, "_value", None)
    return value_container.get() if value_container else 0.0


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

    @patch("posthog.api.exports.ExportedAssetSerializer._start_export_workflow")
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
        created_date = datetime.fromisoformat(data["created_at"]).strftime("%Y-%m-%d-%H%M%S")
        assert data == {
            "id": data["id"],
            "created_at": data["created_at"],
            "dashboard": self.dashboard.id,
            "exception": None,
            "export_format": "image/png",
            "filename": f"export-example-dashboard-{created_date}.png",
            "has_content": False,
            "insight": None,
            "export_context": None,
            # PNG format gets 180 days (6 months) expiry
            "expires_after": (now() + timedelta(days=180))
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }

        mock_exporter_task.assert_called_once()
        assert mock_exporter_task.call_args[0][0].id == data["id"]

    @patch("posthog.api.exports.ExportedAssetSerializer._start_export_workflow")
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

        # Expiry is determined by format (PNG = 180 days), not the provided value
        expected_expiry = (
            (now() + timedelta(days=180))
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

        created_date = datetime.fromisoformat(data["created_at"]).strftime("%Y-%m-%d-%H%M%S")
        assert data == {
            "id": data["id"],
            "created_at": data["created_at"],
            "dashboard": self.dashboard.id,
            "exception": None,
            "export_format": "image/png",
            "filename": f"export-example-dashboard-{created_date}.png",
            "has_content": False,
            "insight": None,
            "export_context": None,
            "expires_after": expected_expiry,
        }

        mock_exporter_task.assert_called_once()
        assert mock_exporter_task.call_args[0][0].id == data["id"]

    @patch("posthog.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_swallow_missing_schema_and_allow_front_end_to_poll(self, mock_exporter_task) -> None:
        # regression test see https://github.com/PostHog/posthog/issues/11204

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
        mock_exporter_task.assert_called_once()
        assert mock_exporter_task.call_args[0][0].id == data["id"]

    @patch("posthog.tasks.exports.image_exporter._export_to_png")
    @patch("posthog.api.exports.ExportedAssetSerializer._start_export_workflow")
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
                "filename": "export-example-insight-2021-08-25-220914.png",
                "has_content": False,
                "dashboard": None,
                "exception": None,
                "export_context": None,
                # PNG format gets 180 days (6 months) expiry
                "expires_after": (now() + timedelta(days=180))
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

        mock_exporter_task.assert_called_once()
        assert mock_exporter_task.call_args[0][0].id == data["id"]

        # look at the page the screenshot will be taken of
        exported_asset = ExportedAsset.objects.get(pk=data["id"])

        with patch("posthog.tasks.exports.image_exporter.calculate_for_query_based_insight") as mock_calculate:
            # Request does not calculate the result and cache is not warmed up
            context = {"is_shared": True}
            InsightSerializer(self.insight, many=False, context=context)

            mock_calculate.assert_not_called()

            # Should warm up the cache
            export_image(exported_asset)
            mock_export_to_png.assert_called_once_with(exported_asset, max_height_pixels=None, insight_cache_keys=ANY)

            mock_calculate.assert_called_once()

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

    @patch("posthog.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_will_error_if_export_unsupported(self, mock_exporter_task) -> None:
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

    @patch("posthog.api.exports.ExportedAssetSerializer._start_export_workflow")
    @patch("posthog.tasks.exports.csv_exporter.requests.request")
    def test_can_download_a_csv(self, patched_request, _mock_workflow) -> None:
        with self.settings(SITE_URL="http://testserver", OBJECT_STORAGE_ENABLED=False):
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
        for item in activity:
            item.pop("id", None)

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
            ("retrieve", "/api/projects/{team_id}/exports/{export_id}"),
            ("content", "/api/projects/{team_id}/exports/{export_id}/content"),
        ]
    )
    def test_cannot_access_other_users_export(self, _name, url_template) -> None:
        export = ExportedAsset.objects.create(
            team=self.team,
            dashboard_id=self.dashboard.id,
            export_format="image/png",
            created_by=self.user,
        )

        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        self.client.force_login(other_user)

        response = self.client.get(url_template.format(team_id=self.team.id, export_id=export.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @parameterized.expand(
        [
            ("retrieve", "/api/projects/{team_id}/exports/{export_id}"),
            ("content", "/api/projects/{team_id}/exports/{export_id}/content"),
        ]
    )
    def test_cannot_access_export_after_losing_resource_access(self, _name, url_template) -> None:
        other_user = User.objects.create_and_join(self.organization, "rbac-test@posthog.com", "password")

        export = ExportedAsset.objects.create(
            team=self.team,
            dashboard_id=self.dashboard.id,
            export_format="image/png",
            created_by=other_user,
        )

        self.organization.available_product_features = [{"key": "advanced_permissions", "name": "Advanced permissions"}]
        self.organization.save()

        AccessControl.objects.create(
            resource="dashboard",
            resource_id=str(self.dashboard.id),
            team=self.team,
            access_level="none",
        )

        self.client.force_login(other_user)
        response = self.client.get(url_template.format(team_id=self.team.id, export_id=export.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @parameterized.expand(
        [
            ("retrieve", "/api/projects/{team_id}/exports/{export_id}"),
            ("content", "/api/projects/{team_id}/exports/{export_id}/content"),
        ]
    )
    def test_cannot_access_session_recording_export_after_losing_access(self, _name, url_template) -> None:
        from posthog.session_recordings.models.session_recording import SessionRecording

        other_user = User.objects.create_and_join(self.organization, "rbac-recording@posthog.com", "password")
        recording = SessionRecording.objects.create(team=self.team, session_id="test-session-123")

        export = ExportedAsset.objects.create(
            team=self.team,
            export_format="video/mp4",
            export_context={"session_recording_id": "test-session-123"},
            created_by=other_user,
        )

        self.organization.available_product_features = [{"key": "advanced_permissions", "name": "Advanced permissions"}]
        self.organization.save()

        AccessControl.objects.create(
            resource="session_recording",
            resource_id=str(recording.id),
            team=self.team,
            access_level="none",
        )

        self.client.force_login(other_user)
        response = self.client.get(url_template.format(team_id=self.team.id, export_id=export.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

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

    @parameterized.expand(
        [
            ("image/png", timedelta(days=180)),
            ("text/csv", timedelta(days=7)),
            ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", timedelta(days=7)),
            ("video/mp4", timedelta(days=365)),
            ("video/webm", timedelta(days=365)),
            ("image/gif", timedelta(days=365)),
            ("application/pdf", timedelta(days=180)),
        ]
    )
    @patch("posthog.api.exports.async_to_sync")
    @patch("posthog.api.exports.async_connect")
    def test_export_expiry_varies_by_format(
        self, export_format, expected_delta, mock_async_connect, mock_async_to_sync
    ) -> None:
        is_video_format = export_format in ("video/mp4", "video/webm", "image/gif")

        if is_video_format:
            payload = {
                "export_format": export_format,
                "export_context": {
                    "session_recording_id": "test_session_123",
                    "timestamp": 100,
                    "duration": 5,
                },
            }
        else:
            payload = {"export_format": export_format, "dashboard": self.dashboard.id}

        response = self.client.post(f"/api/projects/{self.team.id}/exports", payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        expected_expiry = (
            (now() + expected_delta)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

        self.assertEqual(data["expires_after"], expected_expiry)

    @patch("posthog.api.exports.async_to_sync")
    @patch("posthog.api.exports.async_connect")
    def test_video_export_monthly_limit(self, mock_async_connect, mock_async_to_sync) -> None:
        """Test that video exports are limited to 10 per calendar month"""
        # Create 9 video exports this month (we're at the limit - 1)
        for i in range(9):
            ExportedAsset.objects.create(
                team=self.team,
                export_format="video/mp4",
                export_context={"session_recording_id": f"session_{i}"},
                created_by=self.user,
            )

        # The 10th video export should succeed
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "video/mp4",
                "export_context": {
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
    def test_video_export_limit_applies_to_all_video_formats(self, mock_async_connect, mock_async_to_sync) -> None:
        """Test that the limit applies to both MP4 and WebM session recording exports"""
        # Create 5 MP4 and 5 WebM exports this month (at the limit)
        for i in range(5):
            ExportedAsset.objects.create(
                team=self.team,
                export_format="video/mp4",
                export_context={"session_recording_id": f"session_mp4_{i}"},
                created_by=self.user,
            )
            ExportedAsset.objects.create(
                team=self.team,
                export_format="video/webm",
                export_context={"session_recording_id": f"session_webm_{i}"},
                created_by=self.user,
            )

        # MP4 video export should fail
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "video/mp4",
                "export_context": {
                    "session_recording_id": "session_over_limit",
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # WebM video export should also fail (shared limit)
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "video/webm",
                "export_context": {
                    "session_recording_id": "session_webm_over_limit",
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

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
                export_context={"session_recording_id": f"session_jan_{i}"},
                created_by=self.user,
            )

        # Should fail in January
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "video/mp4",
                "export_context": {
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
                        "session_recording_id": "session_feb_success",
                    },
                },
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch("posthog.api.exports.async_to_sync")
    @patch("posthog.api.exports.async_connect")
    def test_video_export_team_specific_limit(self, mock_async_connect, mock_async_to_sync) -> None:
        """Test that teams can have custom export limits via extra_settings"""
        # Set a custom limit of 3 for this team
        self.team.extra_settings = {"full_video_exports_limit": 3}
        self.team.save()

        # Create 2 video exports (should succeed)
        for i in range(2):
            response = self.client.post(
                f"/api/projects/{self.team.id}/exports",
                {
                    "export_format": "video/mp4",
                    "export_context": {
                        "session_recording_id": f"session_{i}",
                    },
                },
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # The 3rd export should succeed (at the custom limit)
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "video/mp4",
                "export_context": {
                    "session_recording_id": "session_3",
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # The 4th export should fail with the custom limit in error message
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "video/mp4",
                "export_context": {
                    "session_recording_id": "session_4",
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error_data = response.json()
        self.assertEqual(error_data["type"], "validation_error")
        self.assertEqual(error_data["attr"], "export_limit_exceeded")
        self.assertIn("reached the limit of 3 full video exports this month", error_data["detail"])

    @patch("posthog.tasks.exports.image_exporter.export_image")
    def test_export_records_failure_on_query_error(self, mock_export_direct) -> None:
        """Test that export_asset records failure info on the asset when a QueryError occurs.

        The actual export now runs inside a Temporal workflow (tested in
        test_export_workflow.py). This test verifies the underlying exporter
        still records structured failure metadata on the ExportedAsset model.
        """
        from posthog.hogql.errors import QueryError

        mock_export_direct.side_effect = QueryError("Unknown table 'nonexistent_table'")

        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format="image/png",
            insight=self.insight,
            created_by=self.user,
        )
        exporter.export_asset(asset.id)

        asset.refresh_from_db()
        self.assertEqual(asset.exception, "Unknown table 'nonexistent_table'")
        self.assertEqual(asset.exception_type, "QueryError")
        self.assertEqual(asset.failure_type, "user")

    @patch("posthog.api.exports.async_connect")
    def test_workflow_failure_returns_201_with_failed_asset(self, mock_async_connect) -> None:
        mock_client = AsyncMock()
        mock_client.execute_workflow.side_effect = Exception("workflow failed")
        mock_async_connect.return_value = mock_client

        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {"export_format": "text/csv", "insight": self.insight.id},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.json()["has_content"])


class TestExportHeatmapSSRFValidation(APIBaseTest):
    @parameterized.expand(
        [
            ("metadata_endpoint", "http://169.254.169.254/latest/meta-data/"),
            ("localhost", "http://localhost/admin"),
            ("loopback_ip", "http://127.0.0.1:8080/secret"),
            ("private_ip_10", "http://10.0.0.1/internal"),
            ("private_ip_192", "http://192.168.1.1/internal"),
            ("internal_domain", "http://service.cluster.local/api"),
            ("file_scheme", "file:///etc/passwd"),
            ("protocol_relative", "//evil.com/steal-data"),
            ("relative_api_path", "/api/environments/1/heatmap_screenshots/42/content/?width=1400"),
        ]
    )
    def test_rejects_ssrf_heatmap_url(self, _name: str, url: str) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports",
            {
                "export_format": "image/png",
                "export_context": {
                    "heatmap_url": url,
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(
        [
            ("external_url", "https://example.com/page"),
            (
                "screenshot_api_url",
                "https://us.posthog.com/api/environments/1/heatmap_screenshots/42/content/?width=1400",
            ),
        ]
    )
    def test_accepts_valid_heatmap_url(self, _name: str, url: str) -> None:
        import ipaddress

        with (
            patch("posthog.security.url_validation.resolve_host_ips") as mock_resolve,
            patch("posthog.api.exports.ExportedAssetSerializer._start_export_workflow"),
        ):
            mock_resolve.return_value = {ipaddress.ip_address("93.184.216.34")}
            response = self.client.post(
                f"/api/projects/{self.team.id}/exports",
                {
                    "export_format": "image/png",
                    "export_context": {"heatmap_url": url},
                },
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class TestExportMixin(APIBaseTest):
    def _get_export_output(self, path: str) -> list[str]:
        """
        Use this function to test the CSV output of exports in other tests
        """
        with self.settings(SITE_URL="http://testserver", OBJECT_STORAGE_ENABLED=False):
            with (
                patch("posthog.tasks.exports.csv_exporter.requests.request") as patched_request,
                patch("posthog.api.exports.ExportedAssetSerializer._start_export_workflow"),
            ):

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
                # Workflow is mocked so the export content isn't generated during
                # the POST. Run the exporter directly to produce CSV content.
                exporter.export_asset(response.json()["id"])

                download_response = self.client.get(
                    f"/api/projects/{self.team.id}/exports/{response.json()['id']}/content?download=true"
                )
                return [str(x) for x in download_response.content.splitlines()]


class TestExportAssetCounters(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.registry = CollectorRegistry()
        self.success_counter = Counter("test_success", "Test", labelnames=["type"], registry=self.registry)
        self.failed_counter = Counter(
            "test_failed", "Test", labelnames=["type", "failure_type"], registry=self.registry
        )
        self.asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
        )

    @parameterized.expand(
        [
            # (error, failure_type, expected_success, expected_failure, expects_exception)
            # Success case
            (None, FAILURE_TYPE_USER, 1.0, 0.0, False),
            # User error: recorded but not raised
            (QueryError("Invalid query"), FAILURE_TYPE_USER, 0.0, 1.0, False),
            # System error: retried by tenacity, then recorded (not raised, swallowed by export_asset)
            (CHQueryErrorTooManySimultaneousQueries("err"), FAILURE_TYPE_SYSTEM, 0.0, 1.0, False),
        ],
        name_func=lambda func, num, params: f"{func.__name__}_{['success', 'user_error', 'system_error'][int(num)]}",
    )
    def test_export_counter_behavior(
        self,
        error: Exception | None,
        failure_type: str,
        expected_success: float,
        expected_failure: float,
        expects_exception: bool,
    ) -> None:
        exception_context = pytest.raises(type(error)) if expects_exception and error else nullcontext()

        with (
            patch("posthog.tasks.exports.image_exporter.export_image", side_effect=error),
            patch.object(exporter, "EXPORT_SUCCEEDED_COUNTER", self.success_counter),
            patch.object(exporter, "EXPORT_FAILED_COUNTER", self.failed_counter),
            patch("time.sleep"),  # Avoid real tenacity backoff waits
            exception_context,
        ):
            exporter.export_asset(self.asset.id)

        assert get_counter_value(self.success_counter, {"type": ExportedAsset.ExportFormat.PNG}) == expected_success
        assert (
            get_counter_value(
                self.failed_counter, {"type": ExportedAsset.ExportFormat.PNG, "failure_type": failure_type}
            )
            == expected_failure
        )
