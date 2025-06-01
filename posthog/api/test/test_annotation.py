from datetime import datetime, timedelta
from unittest.mock import patch

from zoneinfo import ZoneInfo
from django.utils.timezone import now
from rest_framework import status
from parameterized import parameterized

from posthog.models import Annotation, Organization, Team, User
from posthog.test.base import (
    APIBaseTest,
    QueryMatchingTest,
    snapshot_postgres_queries_context,
    FuzzyInt,
)


class TestAnnotation(APIBaseTest, QueryMatchingTest):
    @patch("posthog.api.annotation.report_user_action")
    def test_retrieving_annotation(self, mock_capture):
        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_at="2020-01-04T12:00:00Z",
            content="hello world!",
        )

        # Annotation creation is not reported to PostHog because it has no created_by
        mock_capture.assert_not_called()

        response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["content"], "hello world!")

    @patch("posthog.api.annotation.report_user_action")
    def test_retrieving_annotation_is_not_n_plus_1(self, _mock_capture) -> None:
        """
        see https://sentry.io/organizations/posthog/issues/3706110236/events/db0167ece56649f59b013cbe9de7ba7a/?project=1899813
        """
        with self.assertNumQueries(FuzzyInt(8, 9)), snapshot_postgres_queries_context(self):
            response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()
            self.assertEqual(len(response["results"]), 0)

        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_at="2020-01-04T12:00:00Z",
            created_by=User.objects.create_and_join(self.organization, "one", ""),
            content=now().isoformat(),
        )

        with self.assertNumQueries(FuzzyInt(8, 9)), snapshot_postgres_queries_context(self):
            response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()
            self.assertEqual(len(response["results"]), 1)

        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_at="2020-01-04T12:00:00Z",
            created_by=User.objects.create_and_join(self.organization, "two", ""),
            content=now().isoformat(),
        )

        with self.assertNumQueries(FuzzyInt(8, 9)), snapshot_postgres_queries_context(self):
            response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()
            self.assertEqual(len(response["results"]), 2)

    def test_org_scoped_annotations_are_returned_between_projects(self):
        second_team = Team.objects.create(organization=self.organization, name="Second team")
        Annotation.objects.create(
            organization=self.organization,
            team=second_team,
            created_by=self.user,
            content="Cross-project annotation!",
            scope=Annotation.Scope.ORGANIZATION,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()

        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["content"], "Cross-project annotation!")

    def test_cannot_fetch_annotations_of_org_user_does_not_belong_to(self):
        separate_org, _, separate_team = Organization.objects.bootstrap(None, name="Second team")
        Annotation.objects.create(
            organization=separate_org,
            team=separate_team,
            content="Intra-project annotation!",
            scope=Annotation.Scope.PROJECT,
        )
        Annotation.objects.create(
            organization=separate_org,
            team=separate_team,
            content="Cross-project annotation!",
            scope=Annotation.Scope.ORGANIZATION,
        )

        response_1 = self.client.get(f"/api/projects/{separate_team.id}/annotations/")

        self.assertEqual(response_1.status_code, 403)
        self.assertEqual(
            response_1.json(),
            self.permission_denied_response("You don't have access to the project."),
        )

        response_2 = self.client.get(f"/api/projects/{self.team.id}/annotations/")

        self.assertEqual(response_2.status_code, 200)
        self.assertEqual(response_2.json()["results"], [])

    @patch("posthog.api.annotation.report_user_action")
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
        date_marker: datetime = datetime(2020, 1, 1, 0, 0, 0).replace(tzinfo=ZoneInfo("UTC"))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = Annotation.objects.get(pk=response.json()["id"])
        self.assertEqual(instance.content, "Marketing campaign")
        self.assertEqual(instance.scope, "organization")
        self.assertEqual(instance.date_marker, date_marker)
        self.assertEqual(instance.team, self.team)
        self.assertEqual(instance.creation_type, "USR")

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user,
            "annotation created",
            {"scope": "organization", "date_marker": date_marker},
        )

    @patch("posthog.api.annotation.report_user_action")
    def test_can_create_annotations_as_a_bot(self, mock_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "content": "Marketing campaign",
                "scope": "organization",
                "date_marker": "2020-01-01T00:00:00.000000Z",
                "team": self.team.pk,
                "creation_type": "GIT",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        instance = Annotation.objects.get(pk=response.json()["id"])
        assert instance.creation_type == "GIT"

        get_created_response = self.client.get(f"/api/projects/{self.team.id}/annotations/{instance.id}/")
        assert get_created_response.json()["creation_type"] == "GIT"

    @patch("posthog.api.annotation.report_user_action")
    def test_downgrading_scope_from_org_to_project_uses_team_id_from_api(self, mock_capture):
        second_team = Team.objects.create(organization=self.organization, name="Second team")
        test_annotation = Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            content="hello world!",
            scope=Annotation.Scope.ORGANIZATION,
        )
        mock_capture.reset_mock()  # Disregard the "annotation created" call
        self.client.force_login(self.user)

        response = self.client.patch(
            f"/api/projects/{second_team.id}/annotations/{test_annotation.pk}/",
            {"scope": Annotation.Scope.PROJECT},
        )
        test_annotation.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(test_annotation.scope, Annotation.Scope.PROJECT)
        # Previously the project was `self.team``, but after downgrading scope from "Organization" to "Project", we want
        # the current project (i.e. `second_team`, whose ID was used in the API request) to own the annotation.
        # This is so that an annotation doesn't disappear when its downgraded and it actually belonged to a different
        # project than the one the user is viewing.
        self.assertEqual(test_annotation.team, second_team)

    def test_updating_annotation(self):
        test_annotation = Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            created_at="2020-01-04T12:00:00Z",
            content="hello world!",
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/annotations/{test_annotation.pk}/",
            {"content": "Updated text", "scope": "organization"},
        )
        test_annotation.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(test_annotation.content, "Updated text")
        self.assertEqual(test_annotation.scope, "organization")
        self.assertEqual(test_annotation.date_marker, None)

    def test_deleting_annotation(self):
        new_user = User.objects.create_and_join(self.organization, "new_annotations@posthog.com", None)

        instance = Annotation.objects.create(organization=self.organization, team=self.team, created_by=self.user)
        self.client.force_login(new_user)

        with patch("posthog.api.team.report_user_action"):
            response = self.client.delete(f"/api/projects/{self.team.id}/annotations/{instance.pk}/")

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(Annotation.objects.filter(pk=instance.pk).exists())

    @parameterized.expand(
        [
            (Annotation.Scope.PROJECT, True, True),
            (Annotation.Scope.ORGANIZATION, True, True),
            (Annotation.Scope.PROJECT, False, True),
            (Annotation.Scope.ORGANIZATION, False, True),
        ]
    )
    def test_filter_annotations_by_date_range_and_scope(self, scope, in_date_range, should_be_visible):
        session_start = datetime(2023, 1, 1, 10, 0, 0, tzinfo=ZoneInfo("UTC"))
        session_end = datetime(2023, 1, 1, 11, 0, 0, tzinfo=ZoneInfo("UTC"))

        annotation_date = session_start + timedelta(minutes=30) if in_date_range else session_start - timedelta(hours=1)

        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            content=f"Test annotation - {scope} scope",
            scope=scope,
            date_marker=annotation_date,
        )

        # Query with date range filter (simulating session replay time range)
        response = self.client.get(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "date_from": session_start.isoformat(),
                "date_to": session_end.isoformat(),
                "scope": scope,
            },
        )

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]

        if in_date_range and should_be_visible:
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["content"], f"Test annotation - {scope} scope")
            self.assertEqual(results[0]["scope"], scope)
        else:
            self.assertEqual(len(results), 0)

    def test_filter_annotations_for_session_replay_scenario(self):
        # Session replay scenario: 1-hour recording from 10:00 to 11:00
        session_start = datetime(2023, 1, 1, 10, 0, 0, tzinfo=ZoneInfo("UTC"))
        session_end = datetime(2023, 1, 1, 11, 0, 0, tzinfo=ZoneInfo("UTC"))

        annotations_data = [
            (session_start + timedelta(minutes=15), Annotation.Scope.PROJECT, "Project annotation at 15min"),
            (session_start + timedelta(minutes=30), Annotation.Scope.ORGANIZATION, "Org annotation at 30min"),
            (session_start + timedelta(minutes=45), Annotation.Scope.PROJECT, "Project annotation at 45min"),
            # Outside session time range (should not appear)
            (session_start - timedelta(minutes=30), Annotation.Scope.PROJECT, "Before session"),
            (session_end + timedelta(minutes=30), Annotation.Scope.ORGANIZATION, "After session"),
        ]

        for date_marker, scope, content in annotations_data:
            Annotation.objects.create(
                organization=self.organization,
                team=self.team,
                created_by=self.user,
                content=content,
                scope=scope,
                date_marker=date_marker,
            )

        # Test: Get all annotations within session time range
        response = self.client.get(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "date_from": session_start.isoformat(),
                "date_to": session_end.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]

        # Should get 3 annotations (the ones within the time range)
        self.assertEqual(len(results), 3)

        # Verify they're ordered by date_marker (newest first based on existing ordering)
        contents = [r["content"] for r in results]
        self.assertIn("Project annotation at 15min", contents)
        self.assertIn("Org annotation at 30min", contents)
        self.assertIn("Project annotation at 45min", contents)
        self.assertNotIn("Before session", contents)
        self.assertNotIn("After session", contents)

        # Test: Filter by specific scope within time range
        response_project_only = self.client.get(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "date_from": session_start.isoformat(),
                "date_to": session_end.isoformat(),
                "scope": Annotation.Scope.PROJECT,
            },
        )

        self.assertEqual(response_project_only.status_code, 200)
        project_results = response_project_only.json()["results"]

        # Should get 2 project-scoped annotations
        self.assertEqual(len(project_results), 2)
        project_contents = [r["content"] for r in project_results]
        self.assertIn("Project annotation at 15min", project_contents)
        self.assertIn("Project annotation at 45min", project_contents)
        self.assertNotIn("Org annotation at 30min", project_contents)
