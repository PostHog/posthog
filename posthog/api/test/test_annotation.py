from datetime import datetime
from unittest.mock import patch

import pytz
from django.utils import timezone
from rest_framework import status

from posthog.models import Annotation, Dashboard, DashboardItem, Organization, User
from posthog.test.base import APIBaseTest, BaseTest


class TestAnnotation(BaseTest):
    TESTS_API = True

    @patch("posthoganalytics.capture")
    def test_retrieving_annotation(self, mock_capture):
        Annotation.objects.create(organization=self.organization, team=self.team, content="hello")

        # Annotation creation is not reported to PostHog because it has no created_by
        mock_capture.assert_not_called()

        response = self.client.get("/api/annotation/").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["content"], "hello")

    @patch("posthoganalytics.capture")
    def test_creating_and_retrieving_annotations_by_dashboard_item(self, mock_capture):

        dashboard = Dashboard.objects.create(name="Default", pinned=True, team=self.team,)

        dashboardItem = DashboardItem.objects.create(
            team=self.team, dashboard=dashboard, name="Pageviews this week", last_refresh=timezone.now(),
        )
        Annotation.objects.create(
            team=self.team, created_by=self.user, content="hello", dashboard_item=dashboardItem,
        )
        response = self.client.get("/api/annotation/?dashboard_item=1").json()

        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["content"], "hello")

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user.distinct_id, "annotation created", {"scope": "dashboard_item", "date_marker": None},
        )

    def test_query_annotations_by_datetime(self):

        Annotation.objects.create(
            team=self.team, created_by=self.user, content="hello_early", created_at="2020-01-04T13:00:01Z",
        )
        Annotation.objects.create(
            team=self.team, created_by=self.user, content="hello_later", created_at="2020-01-06T13:00:01Z",
        )
        response = self.client.get("/api/annotation/?before=2020-01-05").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["content"], "hello_early")

        response = self.client.get("/api/annotation/?after=2020-01-05").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["content"], "hello_later")


class TestAPIAnnotation(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization, self.team, self.user = User.objects.bootstrap("Test", "annotations@posthog.com", None)
        self.annotation = Annotation.objects.create(
            organization=self.organization, team=self.team, created_by=self.user,
        )

    @patch("posthoganalytics.capture")
    def test_creating_annotation(self, mock_capture):
        team2 = Organization.objects.bootstrap(None)[2]

        self.client.force_login(self.user)

        response = self.client.post(
            "/api/annotation/",
            {
                "content": "Marketing campaign",
                "scope": "organization",
                "date_marker": "2020-01-01T00:00:00.000000Z",
                "team": team2.pk,  # make sure this is set automatically
            },
        )
        date_marker: datetime = datetime(2020, 1, 1, 0, 0, 0).replace(tzinfo=pytz.UTC)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = Annotation.objects.get(pk=response.data["id"])  # type: ignore
        self.assertEqual(instance.content, "Marketing campaign")
        self.assertEqual(instance.scope, "organization")
        self.assertEqual(instance.date_marker, date_marker)
        self.assertEqual(instance.team, self.team)

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user.distinct_id, "annotation created", {"scope": "organization", "date_marker": date_marker},
        )

    @patch("posthoganalytics.capture")
    def test_updating_annotation(self, mock_capture):
        instance = self.annotation
        self.client.force_login(self.user)

        response = self.client.patch(
            f"/api/annotation/{instance.pk}/", {"content": "Updated text", "scope": "organization"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        instance.refresh_from_db()
        self.assertEqual(instance.content, "Updated text")
        self.assertEqual(instance.scope, "organization")
        self.assertEqual(instance.date_marker, None)

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user.distinct_id, "annotation updated", {"scope": "organization", "date_marker": None},
        )

    def test_deleting_annotation(self):
        new_user = User.objects.create_and_join(self.organization, "new_annotations@posthog.com", None)

        instance = Annotation.objects.create(team=self.team, created_by=self.user)
        self.client.force_login(new_user)

        with patch("posthoganalytics.capture") as mock_capture:
            response = self.client.delete(f"/api/annotation/{instance.pk}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Annotation.objects.filter(pk=instance.pk).exists())

        # Assert analytics are sent (notice the event is sent on the user that executed the deletion, not the creator)
        mock_capture.assert_called_once_with(
            new_user.distinct_id, "annotation deleted", {"scope": "dashboard_item", "date_marker": None},
        )
