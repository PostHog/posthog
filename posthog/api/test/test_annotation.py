from datetime import datetime, timedelta
from typing import Optional
from unittest import mock
from unittest.mock import MagicMock, patch

from zoneinfo import ZoneInfo
from django.utils.timezone import now
from rest_framework import status
from parameterized import parameterized

from posthog.models import Annotation, Organization, Team, User
from posthog.models.utils import uuid7
from posthog.test.base import (
    APIBaseTest,
    QueryMatchingTest,
    snapshot_postgres_queries_context,
    FuzzyInt,
)


class TestAnnotation(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        self.other_user = User.objects.create(email="paul@not-first-user.com")

    @patch("posthog.api.annotation.report_user_action")
    def test_retrieving_annotation(self, mock_capture: MagicMock) -> None:
        created_annotation = Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_at="2020-01-04T12:00:00Z",
            content="hello world!",
            tagged_users=["tomato"],
        )

        # Annotation creation is not reported to PostHog because it has no created_by!
        mock_capture.assert_not_called()

        response = self.client.get(f"/api/projects/{self.team.id}/annotations/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [
                {
                    "content": "hello world!",
                    "created_at": "2020-01-04T12:00:00Z",
                    "created_by": None,
                    "creation_type": "USR",
                    "dashboard_id": None,
                    "dashboard_item": None,
                    "dashboard_name": None,
                    "date_marker": None,
                    "deleted": False,
                    "id": created_annotation.id,
                    "insight_derived_name": None,
                    "insight_name": None,
                    "insight_short_id": None,
                    "is_emoji": False,
                    "recording_id": None,
                    "scope": "dashboard_item",
                    "tagged_users": [
                        "tomato",
                    ],
                    "updated_at": mock.ANY,
                }
            ],
        }

    @patch("posthog.api.annotation.report_user_action")
    def test_retrieving_annotation_is_not_n_plus_1(self, _mock_capture: MagicMock) -> None:
        with self.assertNumQueries(FuzzyInt(8, 9)), snapshot_postgres_queries_context(self):
            response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()
            assert len(response["results"]) == 0

        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_at="2020-01-04T12:00:00Z",
            created_by=User.objects.create_and_join(self.organization, "one", ""),
            content=now().isoformat(),
        )

        with self.assertNumQueries(FuzzyInt(8, 9)), snapshot_postgres_queries_context(self):
            response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()
            assert len(response["results"]) == 1

        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_at="2020-01-04T12:00:00Z",
            created_by=User.objects.create_and_join(self.organization, "two", ""),
            content=now().isoformat(),
        )

        with self.assertNumQueries(FuzzyInt(8, 9)), snapshot_postgres_queries_context(self):
            response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()
            assert len(response["results"]) == 2

    def test_org_scoped_annotations_are_returned_between_projects(self) -> None:
        second_team = Team.objects.create(organization=self.organization, name="Second team")
        Annotation.objects.create(
            organization=self.organization,
            team=second_team,
            created_by=self.user,
            content="Cross-project annotation!",
            scope=Annotation.Scope.ORGANIZATION,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()

        assert len(response["results"]) == 1
        assert response["results"][0]["content"] == "Cross-project annotation!"

    def test_cannot_fetch_annotations_of_org_user_does_not_belong_to(self) -> None:
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

        assert response_1.status_code == 403
        assert response_1.json() == self.permission_denied_response("You don't have access to the project.")

        response_2 = self.client.get(f"/api/projects/{self.team.id}/annotations/")

        assert response_2.status_code == 200
        assert response_2.json()["results"] == []

    @patch("posthog.api.annotation.report_user_action")
    def test_creating_annotation(self, mock_capture: MagicMock) -> None:
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
        assert response.status_code == status.HTTP_201_CREATED
        instance = Annotation.objects.get(pk=response.json()["id"])
        assert instance.content == "Marketing campaign"
        assert instance.scope == "organization"
        assert instance.date_marker == date_marker
        assert instance.team == self.team
        assert instance.creation_type == "USR"

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user,
            "annotation created",
            {"scope": "organization", "date_marker": date_marker},
        )

    @patch("posthog.api.annotation.report_user_action")
    def test_can_create_annotations_as_a_bot(self, mock_capture: MagicMock) -> None:
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
    def test_downgrading_scope_from_org_to_project_uses_team_id_from_api(self, mock_capture: MagicMock) -> None:
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

        assert response.status_code == status.HTTP_200_OK
        assert test_annotation.scope == Annotation.Scope.PROJECT
        # Previously the project was `self.team``, but after downgrading scope from "Organization" to "Project", we want
        # the current project (i.e. `second_team`, whose ID was used in the API request) to own the annotation.
        # This is so that an annotation doesn't disappear when its downgraded and it actually belonged to a different
        # project than the one the user is viewing.
        assert test_annotation.team == second_team

    def test_updating_annotation(self) -> None:
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

        assert response.status_code == status.HTTP_200_OK
        assert test_annotation.content == "Updated text"
        assert test_annotation.scope == "organization"
        assert test_annotation.date_marker is None

    def test_deleting_annotation(self) -> None:
        new_user = User.objects.create_and_join(self.organization, "new_annotations@posthog.com", None)

        instance = Annotation.objects.create(organization=self.organization, team=self.team, created_by=self.user)
        self.client.force_login(new_user)

        with patch("posthog.api.team.report_user_action"):
            response = self.client.delete(f"/api/projects/{self.team.id}/annotations/{instance.pk}/")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert Annotation.objects.filter(pk=instance.pk).exists()

    @parameterized.expand(
        [
            ("organization", "organization scoped", 1),
            ("project", "project scoped", 1),
            ("insight", "insight scoped", 1),
            ("dashboard_item", "insight scoped", 1),
            ("dashboard", "dashboard scoped", 1),
            (None, None, 4),
        ]
    )
    def test_annotation_can_be_filtered_by_scope(
        self, scope: Optional[str], expected_content: Optional[str], expected_result_count: int
    ) -> None:
        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            content="organization scoped",
            scope=Annotation.Scope.ORGANIZATION,
        )
        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            content="project scoped",
            scope=Annotation.Scope.PROJECT,
        )
        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            content="insight scoped",
            scope=Annotation.Scope.INSIGHT,
        )
        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            content="dashboard scoped",
            scope=Annotation.Scope.DASHBOARD,
        )

        scope_query_param = f"?scope={scope}" if scope else ""
        response = self.client.get(f"/api/projects/{self.team.id}/annotations/{scope_query_param}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert len(response.json()["results"]) == expected_result_count
        if expected_result_count == 1:
            assert response.json()["results"][0]["content"] == expected_content

    @parameterized.expand(
        [
            # Test case: (scope, should_be_visible_in_date_range, should_be_visible_in_scope_filter)
            (Annotation.Scope.PROJECT, True, True),
            (Annotation.Scope.ORGANIZATION, True, True),
            (Annotation.Scope.PROJECT, False, True),  # Outside date range
            (Annotation.Scope.ORGANIZATION, False, True),  # Outside date range
        ]
    )
    def test_filter_annotations_by_date_range_and_scope(
        self, scope: str, in_date_range: bool, should_be_visible: bool
    ) -> None:
        """Test that annotations can be filtered by date range and scope for session replay integration."""

        # Create base dates for our test
        session_start = datetime(2023, 1, 1, 10, 0, 0, tzinfo=ZoneInfo("UTC"))
        session_end = datetime(2023, 1, 1, 11, 0, 0, tzinfo=ZoneInfo("UTC"))

        # Create an annotation either inside or outside the session date range
        annotation_date = session_start + timedelta(minutes=30) if in_date_range else session_start - timedelta(hours=1)

        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            content=f"Test annotation - {scope} scope",
            scope=scope,
            date_marker=annotation_date,
        )

        # Query with a date range filter (simulating session replay time range)
        response = self.client.get(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "date_from": session_start.isoformat(),
                "date_to": session_end.isoformat(),
                "scope": scope,
            },
        )

        assert response.status_code == 200
        results = response.json()["results"]

        if in_date_range and should_be_visible:
            assert len(results) == 1
            assert results[0]["content"] == f"Test annotation - {scope} scope"
            assert results[0]["scope"] == scope
        else:
            assert len(results) == 0

    def test_filter_annotations_for_session_replay_scenario(self) -> None:
        """Test a realistic session replay scenario with multiple annotations and scopes."""

        # Session replay scenario: 1-hour recording from 10:00 to 11:00
        session_start = datetime(2023, 1, 1, 10, 0, 0, tzinfo=ZoneInfo("UTC"))
        session_end = datetime(2023, 1, 1, 11, 0, 0, tzinfo=ZoneInfo("UTC"))

        # Create annotations at different times and scopes
        annotations_data = [
            # Inside session time range
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

        # Test: Get all annotations within the session time range
        response = self.client.get(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "date_from": session_start.isoformat(),
                "date_to": session_end.isoformat(),
            },
        )

        assert response.status_code == 200
        results = response.json()["results"]

        # Should get 3 annotations (the ones within the time range)
        assert len(results) == 3

        # Verify they're ordered by date_marker (newest first based on existing ordering)
        contents = [r["content"] for r in results]
        assert "Project annotation at 15min" in contents
        assert "Org annotation at 30min" in contents
        assert "Project annotation at 45min" in contents
        assert "Before session" not in contents
        assert "After session" not in contents

        # Test: Filter by specific scope within time range
        response_project_only = self.client.get(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "date_from": session_start.isoformat(),
                "date_to": session_end.isoformat(),
                "scope": Annotation.Scope.PROJECT,
            },
        )

        assert response_project_only.status_code == 200
        project_results = response_project_only.json()["results"]

        # Should get 2 project-scoped annotations
        assert len(project_results) == 2
        project_contents = [r["content"] for r in project_results]
        assert "Project annotation at 15min" in project_contents
        assert "Project annotation at 45min" in project_contents
        assert "Org annotation at 30min" not in project_contents

    def test_filter_annotations_400_for_invalid_scope(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/annotations/",
            {"scope": "invalid_scope"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid scope: invalid_scope"

    @parameterized.expand(
        [
            ("invalid_date", "2024-01-01T11:00:00Z", "date_from must be a valid ISO 8601 date"),
            ("2024-01-01T11:00:00Z", "invalid_date", "date_to must be a valid ISO 8601 date"),
            ("2024-01-01T11:00:00Z", "2024-01-01T10:00:00Z", "date_from must be before date_to"),
        ]
    )
    def test_filter_annotations_400_for_invalid_date_range(
        self, date_from: str, date_to: str, error_message: str
    ) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/annotations/",
            {"date_from": date_from, "date_to": date_to},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == f"Invalid date range: {error_message}"

    def test_filter_annotations_by_specific_recording(self) -> None:
        annotation = Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            content="Test annotation",
            scope=Annotation.Scope.RECORDING,
            recording_id="123e4567-e89b-12d3-a456-426614174000",
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/annotations/",
            {"recording": "123e4567-e89b-12d3-a456-426614174000"},
        )
        assert response.status_code == 200
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == annotation.id

    @parameterized.expand(
        [
            ("true", True),  # Filter for emoji annotations
            ("false", False),  # Filter for non-emoji annotations
            ("1", True),  # Alternative true value
            ("0", False),  # Alternative false value
        ]
    )
    def test_filter_annotations_by_is_emoji(self, is_emoji_param: str, should_return_emoji: bool) -> None:
        """Test filtering annotations by is_emoji parameter."""
        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            content="😊",
            is_emoji=True,
            scope=Annotation.Scope.DASHBOARD,
            recording_id="123e4567-e89b-12d3-a456-426614174000",
        )

        emoji_annotation = Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            content="😊",
            is_emoji=True,
            scope=Annotation.Scope.RECORDING,
            recording_id="123e4567-e89b-12d3-a456-426614174000",
        )

        # Create non-emoji annotation
        text_annotation = Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            content="Text annotation",
            is_emoji=False,
            scope=Annotation.Scope.RECORDING,
            recording_id="123e4567-e89b-12d3-a456-426614174000",
        )

        # Test filtering by is_emoji parameter
        response = self.client.get(
            f"/api/projects/{self.team.id}/annotations/",
            {"is_emoji": is_emoji_param, "scope": "recording"},
        )

        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 1

        if should_return_emoji:
            assert results[0]["id"] == emoji_annotation.id
            assert results[0]["content"] == "😊"
            assert results[0]["is_emoji"] is True
        else:
            assert results[0]["id"] == text_annotation.id
            assert results[0]["content"] == "Text annotation"
            assert results[0]["is_emoji"] is False

    def test_filter_annotations_by_is_emoji_combined_with_other_filters(self) -> None:
        """Test combining is_emoji filter with scope and recording filters."""
        # Create emoji annotation for recording - this should be returned
        emoji_recording = Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            content="🚀",
            is_emoji=True,
            scope=Annotation.Scope.RECORDING,
            recording_id="123e4567-e89b-12d3-a456-426614174000",
        )

        # Create emoji annotation for project (different scope) - should not be returned
        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            content="⭐",
            is_emoji=True,
            scope=Annotation.Scope.PROJECT,
        )

        # Create non-emoji annotation for recording - should not be returned
        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            content="Text note",
            is_emoji=False,
            scope=Annotation.Scope.RECORDING,
            recording_id="123e4567-e89b-12d3-a456-426614174000",
        )

        # Test: Filter for emoji annotations on recordings only
        response = self.client.get(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "is_emoji": "true",
                "scope": "recording",
                "recording": "123e4567-e89b-12d3-a456-426614174000",
            },
        )

        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] == emoji_recording.id
        assert results[0]["content"] == "🚀"
        assert results[0]["is_emoji"] is True
        assert results[0]["scope"] == "recording"

    @parameterized.expand(
        [
            ("Standard emoji", "😊", True, None),
            ("Another emoji", "🚀", True, None),
            ("Single letter", "a", False, "When is_emoji is True, content must be a single emoji"),
            ("Single digit", "1", False, "When is_emoji is True, content must be a single emoji"),
            ("Single symbol", "!", False, "When is_emoji is True, content must be a single emoji"),
            ("Empty string", "", False, "When is_emoji is True, content cannot be empty"),
            ("Multiple characters", "ab", False, "When is_emoji is True, content must be a single emoji"),
            ("Multiple emojis", "😊😊", False, "When is_emoji is True, content must be a single emoji"),
            ("No content", None, False, "When is_emoji is True, content cannot be empty"),
        ]
    )
    def test_create_annotation_emoji_validation(
        self, _name: str, content: Optional[str], should_succeed: bool, error: str
    ) -> None:
        """Test emoji validation when creating annotations with is_emoji=True."""
        data = {
            "is_emoji": True,
            "scope": "project",
            "date_marker": "2020-01-01T00:00:00.000000Z",
        }
        if content is not None:
            data["content"] = content

        response = self.client.post(f"/api/projects/{self.team.id}/annotations/", data)

        if should_succeed:
            assert response.status_code == status.HTTP_201_CREATED
            instance = Annotation.objects.get(pk=response.json()["id"])
            assert instance.content == content
            assert instance.is_emoji is True
        else:
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert response.json()["detail"] == error

    @parameterized.expand(
        [
            ("Valid emoji", "🚀", True, None),
            ("Invalid for emoji", "multiple chars", False, "When is_emoji is True, content must be a single emoji"),
            ("Empty string", "", False, "When is_emoji is True, content cannot be empty"),
            ("Single symbol", "!", False, "When is_emoji is True, content must be a single emoji"),
        ]
    )
    def test_update_annotation_emoji_validation(
        self, _name: str, content: str, should_succeed: bool, error: str | None
    ) -> None:
        """Test emoji validation when updating annotations with is_emoji=True."""
        annotation = Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            content="old content",
            is_emoji=False,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/annotations/{annotation.pk}/",
            {"content": content, "is_emoji": True},
        )

        if should_succeed:
            assert response.status_code == status.HTTP_200_OK
            annotation.refresh_from_db()
            assert annotation.content == content
            assert annotation.is_emoji is True
        else:
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert response.json()["detail"] == error

    def test_create_annotation_with_tagged_users(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "content": "Original content with @a_user",
                "tagged_users": [str(self.user.uuid)],
                "scope": "project",
                "date_marker": "2020-01-01T00:00:00.000000Z",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED

        annotation = Annotation.objects.get(pk=response.json()["id"])
        assert annotation.tagged_users == [str(self.user.uuid)]
        assert response.json()["tagged_users"] == [str(self.user.uuid)]

    def test_create_annotation_tagged_users_must_be_valid_uuid(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "content": "Original content with @a_user",
                "tagged_users": ["not a uuid"],
                "scope": "project",
                "date_marker": "2020-01-01T00:00:00.000000Z",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

        assert response.json() == {
            "attr": None,
            "code": "invalid_input",
            "detail": "“not a uuid” is not a valid UUID.",
            "type": "validation_error",
        }

    def test_update_annotation_with_tagged_users(self) -> None:
        annotation = Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            content="Original content with @old_user",
            tagged_users=[str(uuid7()), str(self.user.uuid)],
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/annotations/{annotation.pk}/",
            {
                "content": "Updated content with @old_user",
                "tagged_users": [str(self.user.uuid), str(self.user.uuid), str(uuid7())],
            },
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

        annotation.refresh_from_db()
        assert annotation.tagged_users == [str(self.user.uuid), str(self.user.uuid)]
        assert response.json()["tagged_users"] == [str(self.user.uuid), str(self.user.uuid)]

    def test_activity_logging_when_users_tagged_in_annotation(self) -> None:
        content = "Important annotation with @alice and @bob"
        tagged_users = [str(self.user.uuid), str(self.other_user.uuid)]

        response = self.client.post(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "content": content,
                "tagged_users": tagged_users,
                "scope": "project",
                "date_marker": "2020-01-01T00:00:00.000000Z",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED

        self._assert_single_entry_activity_log(
            {
                "scope": "annotation",
                "item_id": str(response.json()["id"]),
            },
            detail_override={
                "name": str(self.user.uuid),
            },
            changes_override={
                "type": "project",
            },
            changes_after_override={
                "annotation_content": "Important annotation with @alice and @bob",
                "annotation_scope": "project",
                "tagged_user": str(self.user.uuid),
            },
        )

    def test_activity_logging_when_users_tagged_in_recording_comment(self) -> None:
        content = "Recording comment with @alice"
        tagged_users = [str(self.user.uuid)]
        recording_id = str(uuid7())
        response = self.client.post(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "content": content,
                "tagged_users": tagged_users,
                "scope": "recording",
                "recording_id": recording_id,
                "date_marker": "2020-01-01T00:00:00.000000Z",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()

        self._assert_single_entry_activity_log(
            {
                "scope": "Replay",
                "item_id": str(response.json()["id"]),
            },
            detail_override={
                "name": str(self.user.uuid),
            },
            changes_override={
                "type": "Replay",
            },
            changes_after_override={
                "annotation_recording_id": recording_id,
                "annotation_content": content,
                "annotation_scope": "recording",
                "tagged_user": str(self.user.uuid),
            },
        )

    def test_activity_logging_when_updating_tagged_users(self) -> None:
        unknown_user = str(uuid7())
        annotation = Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            content="Original content with @old_user",
            tagged_users=[unknown_user],
            scope="organization",
        )

        # Update to add new tagged user
        response = self.client.patch(
            f"/api/projects/{self.team.id}/annotations/{annotation.pk}/",
            {
                "content": "Updated content with @old_user and @new_user",
                "tagged_users": [unknown_user, str(self.user.uuid)],
            },
        )

        assert response.status_code == status.HTTP_200_OK

        self._assert_single_entry_activity_log(
            {
                "scope": "annotation",
                "item_id": str(response.json()["id"]),
            },
            detail_override={
                "name": str(self.user.uuid),
            },
            changes_override={
                "type": "organization",
            },
            changes_after_override={
                "annotation_content": "Updated content with @old_user and @new_user",
                "annotation_scope": "organization",
                "tagged_user": str(self.user.uuid),
            },
        )

    def _assert_single_entry_activity_log(
        self, log_override: dict, detail_override: dict, changes_override: dict, changes_after_override: dict
    ):
        annotations_response = self.client.get(f"/api/projects/{self.team.id}/activity_log/")
        assert annotations_response.status_code == status.HTTP_200_OK
        assert annotations_response.json()["results"] == [
            {
                "activity": "tagged_user",
                "created_at": mock.ANY,
                "detail": {
                    "changes": [
                        {
                            "action": "tagged_user",
                            "after": {
                                "annotation_dashboard_id": None,
                                "annotation_insight_id": None,
                                "annotation_recording_id": None,
                                "annotation_scope": None,
                                "tagged_user": None,
                                **changes_after_override,
                            },
                            "before": None,
                            "field": None,
                            "type": None,
                            **changes_override,
                        }
                    ],
                    "name": None,
                    "short_id": None,
                    "trigger": None,
                    "type": None,
                    **detail_override,
                },
                "id": mock.ANY,
                "is_system": False,
                "item_id": None,
                "organization_id": str(self.team.organization_id),
                "scope": None,
                "unread": False,
                "user": {
                    "distinct_id": self.user.distinct_id,
                    "email": self.user.email,
                    "first_name": "",
                    "hedgehog_config": None,
                    "id": self.user.id,
                    "is_email_verified": None,
                    "last_name": "",
                    "role_at_organization": None,
                    "uuid": str(self.user.uuid),
                },
                "was_impersonated": False,
                **log_override,
            }
        ]
