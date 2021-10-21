from datetime import datetime
from unittest.mock import patch

import pytz
from django.utils import timezone
from rest_framework import status

from posthog.models import Annotation, Dashboard, Insight, Organization, User, organization
from posthog.models.team import Team
from posthog.test.base import APIBaseTest


class TestAnnotation(APIBaseTest):
    annotation: Annotation = None  # type: ignore

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.annotation = Annotation.objects.create(
            organization=cls.organization,
            team=cls.team,
            created_by=cls.user,
            created_at="2020-01-04T12:00:00Z",
            content="hello world!",
        )

    @patch("posthoganalytics.capture")
    def test_retrieving_annotation(self, mock_capture):
        # Annotation creation is not reported to PostHog because it has no created_by
        mock_capture.assert_not_called()

        response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["content"], "hello world!")

    @patch("posthoganalytics.capture")
    def test_creating_and_retrieving_annotations_by_dashboard_item(self, mock_capture):

        dashboard = Dashboard.objects.create(name="Default", pinned=True, team=self.team,)

        dashboard_item = Insight.objects.create(
            team=self.team, dashboard=dashboard, name="Pageviews this week", last_refresh=timezone.now(),
        )
        Annotation.objects.create(
            team=self.team, created_by=self.user, content="hello", dashboard_item=dashboard_item,
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/annotations/?dashboardItemId={dashboard_item.id}"
        ).json()

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
        response = self.client.get(f"/api/projects/{self.team.id}/annotations/?before=2020-01-05").json()
        self.assertEqual(len(response["results"]), 2)
        self.assertEqual(response["results"][1]["content"], "hello_early")

        response = self.client.get(f"/api/projects/{self.team.id}/annotations/?after=2020-01-05").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["content"], "hello_later")

    @patch("posthoganalytics.capture")
    def test_creating_annotation(self, mock_capture):
        team2 = Organization.objects.bootstrap(None)[2]

        self.client.force_login(self.user)

        response = self.client.post(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "content": "Marketing campaign",
                "scope": "organization",
                "date_marker": "2020-01-01T00:00:00.000000Z",
                "team": team2.pk,  # make sure this is set automatically
            },
        )
        date_marker: datetime = datetime(2020, 1, 1, 0, 0, 0).replace(tzinfo=pytz.UTC)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = Annotation.objects.get(pk=response.json()["id"])
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
            f"/api/projects/{self.team.id}/annotations/{instance.pk}/",
            {"content": "Updated text", "scope": "organization"},
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

    def test_deleting_annotation_of_other_team_prevented(self):
        other_organization, other_team, _ = User.objects.bootstrap("Other Corp", "Juan", None)
        other_annotation = Annotation.objects.create(
            organization=other_organization,
            team=other_team,
            created_by=self.user,
            created_at="2020-01-04T12:00:00Z",
            content="hello world!",
        )
        response_via_other_team = self.client.delete(
            f"/api/projects/{other_team.pk}/annotations/{other_annotation.pk}/"
        )

        self.assertEqual(response_via_other_team.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.permission_denied_response("You don't have access to the project."), response_via_other_team.json()
        )

        response_via_self_team = self.client.delete(f"/api/projects/{self.team.pk}/annotations/{other_annotation.pk}/")

        self.assertEqual(response_via_self_team.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.not_found_response(), response_via_self_team.json())

    def test_deleting_annotation(self):
        new_user = User.objects.create_and_join(self.organization, "new_annotations@posthog.com", None)

        instance = Annotation.objects.create(team=self.team, created_by=self.user)
        self.client.force_login(new_user)

        with patch("posthoganalytics.capture") as mock_capture:
            response = self.client.delete(f"/api/projects/{self.team.id}/annotations/{instance.pk}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Annotation.objects.filter(pk=instance.pk).exists())

        # Assert analytics are sent (notice the event is sent on the user that executed the deletion, not the creator)
        mock_capture.assert_called_once_with(
            new_user.distinct_id, "annotation deleted", {"scope": "dashboard_item", "date_marker": None},
        )
