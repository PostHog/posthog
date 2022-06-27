from typing import Dict, List
from unittest.mock import patch

import celery
from freezegun import freeze_time
from rest_framework import status

from posthog.models.dashboard import Dashboard
from posthog.models.exported_asset import ExportedAsset
from posthog.models.filters.filter import Filter
from posthog.models.insight import Insight
from posthog.models.team import Team
from posthog.test.base import APIBaseTest


@patch("posthog.api.exports.exporter")
class TestExports(APIBaseTest):
    exported_asset: ExportedAsset = None  # type: ignore
    dashboard: Dashboard = None  # type: ignore
    insight: Insight = None  # type: ignore

    insight_filter_dict = {
        "events": [{"id": "$pageview"}],
        "properties": [{"key": "$browser", "value": "Mac OS X"}],
    }

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.dashboard = Dashboard.objects.create(team=cls.team, name="example dashboard", created_by=cls.user)
        cls.insight = Insight.objects.create(
            filters=Filter(data=cls.insight_filter_dict).to_dict(), team=cls.team, created_by=cls.user
        )
        cls.exported_asset = ExportedAsset.objects.create(
            team=cls.team, dashboard_id=cls.dashboard.id, export_format="image/png"
        )

    def test_can_create_new_valid_export_dashboard(self, mock_exporter_task):
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports", {"export_format": "image/png", "dashboard": self.dashboard.id}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(
            data,
            {
                "id": data["id"],
                "created_at": data["created_at"],
                "dashboard": self.dashboard.id,
                "export_format": "image/png",
                "has_content": False,
                "insight": None,
            },
        )

        mock_exporter_task.export_task.delay.assert_called_once_with(data["id"])

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_can_create_new_valid_export_insight(self, mock_exporter_task):
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports", {"export_format": "application/pdf", "insight": self.insight.id}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(
            data,
            {
                "id": data["id"],
                "created_at": data["created_at"],
                "insight": self.insight.id,
                "export_format": "application/pdf",
                "has_content": False,
                "dashboard": None,
            },
        )

        self._assert_logs_the_activity(
            insight_id=self.insight.id,
            expected=[
                {
                    "user": {"first_name": self.user.first_name, "email": self.user.email,},
                    "activity": "exported",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "Insight",
                    "item_id": str(self.insight.id),
                    "detail": {
                        "changes": [
                            {
                                "action": "exported",
                                "after": "application/pdf",
                                "before": None,
                                "field": "export_format",
                                "type": "Insight",
                            }
                        ],
                        "merge": None,
                        "name": self.insight.name,
                        "short_id": self.insight.short_id,
                    },
                }
            ],
        )

        mock_exporter_task.export_task.delay.assert_called_once_with(data["id"])

    def test_errors_if_missing_related_instance(self, mock_tasks):
        response = self.client.post(f"/api/projects/{self.team.id}/exports", {"export_format": "image/png"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "attr": None,
                "code": "invalid_input",
                "detail": "Either dashboard or insight is required for an export.",
                "type": "validation_error",
            },
        )

    def test_errors_if_bad_format(self, mock_tasks):
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

    def test_will_respond_even_if_task_timesout(self, mock_exporter_task):
        mock_exporter_task.export_task.delay.return_value.get.side_effect = celery.exceptions.TimeoutError("timed out")
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports", {"export_format": "application/pdf", "insight": self.insight.id}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_will_error_if_export_unsupported(self, mock_exporter_task):
        mock_exporter_task.export_task.delay.return_value.get.side_effect = NotImplementedError("not implemented")
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports", {"export_format": "application/pdf", "insight": self.insight.id}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "attr": "export_format",
                "code": "invalid_input",
                "detail": "This type of export is not supported for this resource.",
                "type": "validation_error",
            },
        )

    def test_will_error_if_dashboard_missing(self, mock_exporter_task):
        response = self.client.post(
            f"/api/projects/{self.team.id}/exports", {"export_format": "application/pdf", "dashboard": 54321}
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

    def test_will_error_if_export_contains_other_team_dashboard(self, mock_exporter_task):
        other_team = Team.objects.create(
            organization=self.organization,
            api_token=self.CONFIG_API_TOKEN + "2",
            test_account_filters=[
                {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"},
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

    def test_will_error_if_export_contains_other_team_insight(self, mock_exporter_task):
        other_team = Team.objects.create(
            organization=self.organization,
            api_token=self.CONFIG_API_TOKEN + "2",
            test_account_filters=[
                {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"},
            ],
        )
        other_insight = Insight.objects.create(
            filters=Filter(data=self.insight_filter_dict).to_dict(), team=other_team, created_by=self.user
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/exports", {"export_format": "application/pdf", "insight": other_insight.id},
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

    def _get_insight_activity(self, insight_id: int, expected_status: int = status.HTTP_200_OK):
        url = f"/api/projects/{self.team.id}/insights/{insight_id}/activity"
        activity = self.client.get(url)
        self.assertEqual(activity.status_code, expected_status)
        return activity.json()

    def _assert_logs_the_activity(self, insight_id: int, expected: List[Dict]) -> None:
        activity_response = self._get_insight_activity(insight_id)

        activity: List[Dict] = activity_response["results"]

        self.maxDiff = None
        self.assertEqual(
            activity, expected,
        )
