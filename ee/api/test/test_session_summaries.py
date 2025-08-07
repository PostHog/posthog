import os
from datetime import datetime
from typing import Any, Optional
from unittest.mock import patch, MagicMock, Mock

from django.http import HttpResponse
from posthog.test.base import APIBaseTest
from ee.hogai.session_summaries.session_group.patterns import (
    EnrichedSessionGroupSummaryPatternsList,
    EnrichedSessionGroupSummaryPattern,
    EnrichedSessionGroupSummaryPatternStats,
)


class TestSessionSummariesAPI(APIBaseTest):
    url: str
    environment_patches: list[Any]

    def _create_mock_replay_events(
        self,
        sessions_found: set[str],
        min_timestamp: Optional[datetime] = None,
        max_timestamp: Optional[datetime] = None,
    ) -> MagicMock:
        """Helper to create a mock SessionReplayEvents instance with standard behavior."""
        mock_instance = MagicMock()
        return_value: tuple[set[str], Optional[datetime], Optional[datetime]] = (
            sessions_found,
            min_timestamp,
            max_timestamp,
        )
        mock_instance.sessions_found_with_timestamps.return_value = return_value
        return mock_instance

    def _make_api_request(self, session_ids: list[str], focus_area: Optional[str] = None) -> HttpResponse:
        """Helper to make API requests with consistent formatting."""
        payload: dict[str, Any] = {"session_ids": session_ids}
        if focus_area is not None:
            payload["focus_area"] = focus_area
        return self.client.post(self.url, payload, format="json")

    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/environments/{self.team.id}/session_summaries/create_session_summaries/"

        # Mock environment requirements
        self.environment_patches = [
            patch("ee.api.session_summaries.is_cloud", return_value=True),
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
        ]
        for p in self.environment_patches:
            p.start()

    def tearDown(self) -> None:
        super().tearDown()
        for p in self.environment_patches:
            p.stop()

    def create_mock_result(self) -> Any:
        """Create a mock result that mimics the EnrichedSessionGroupSummaryPatternsList object"""
        return EnrichedSessionGroupSummaryPatternsList(
            patterns=[
                EnrichedSessionGroupSummaryPattern(
                    pattern_id=1,
                    pattern_name="Login Flow Pattern",
                    pattern_description="Users attempting to log in with some encountering errors",
                    severity="medium",
                    indicators=["login attempts", "form submissions"],
                    events=[],
                    stats=EnrichedSessionGroupSummaryPatternStats(
                        occurences=2,
                        sessions_affected=2,
                        sessions_affected_ratio=1.0,
                        segments_success_ratio=0.75,
                    ),
                )
            ]
        )

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.SessionReplayEvents")
    @patch("ee.api.session_summaries.execute_summarize_session_group")
    @patch("ee.api.session_summaries.create_summary_notebook")
    def test_create_summaries_success(
        self, mock_create_notebook: Mock, mock_execute: Mock, mock_replay_events: Mock, mock_feature_enabled: Mock
    ) -> None:
        """Test successful creation of session summaries"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_replay_events.return_value = self._create_mock_replay_events(
            sessions_found={"session1", "session2"},
            min_timestamp=datetime(2024, 1, 1, 10, 0, 0),
            max_timestamp=datetime(2024, 1, 1, 11, 0, 0),
        )

        mock_result = self.create_mock_result()
        mock_execute.return_value = mock_result

        # Make request
        response = self._make_api_request(session_ids=["session1", "session2"], focus_area="login process")

        # Assertions
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")

        data: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        # The response is the serialized EnrichedSessionGroupSummaryPatternsList
        self.assertIsInstance(data, dict)
        self.assertIn("patterns", data)
        self.assertEqual(len(data["patterns"]), 1)
        self.assertEqual(data["patterns"][0]["pattern_name"], "Login Flow Pattern")
        self.assertEqual(data["patterns"][0]["severity"], "medium")
        self.assertEqual(data["patterns"][0]["stats"]["occurences"], 2)

        # Verify execute_summarize_session_group was called correctly
        mock_execute.assert_called_once_with(
            session_ids=["session1", "session2"],
            user_id=self.user.pk,
            team=self.team,
            min_timestamp=datetime(2024, 1, 1, 10, 0, 0),
            max_timestamp=datetime(2024, 1, 1, 11, 0, 0),
            extra_summary_context=mock_execute.call_args[1]["extra_summary_context"],
            local_reads_prod=False,
        )
        # Check extra_summary_context separately
        self.assertEqual(mock_execute.call_args[1]["extra_summary_context"].focus_area, "login process")

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.SessionReplayEvents")
    @patch("ee.api.session_summaries.execute_summarize_session_group")
    @patch("ee.api.session_summaries.create_summary_notebook")
    def test_create_summaries_without_focus_area(
        self, mock_create_notebook: Mock, mock_execute: Mock, mock_replay_events: Mock, mock_feature_enabled: Mock
    ) -> None:
        """Test successful creation without focus area"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_replay_events.return_value = self._create_mock_replay_events(
            sessions_found={"session1", "session2"},
            min_timestamp=datetime(2024, 1, 1, 10, 0, 0),
            max_timestamp=datetime(2024, 1, 1, 11, 0, 0),
        )

        mock_result = self.create_mock_result()
        mock_execute.return_value = mock_result

        # Make request without focus_area
        response = self._make_api_request(session_ids=["session1", "session2"])

        # Assertions
        self.assertEqual(response.status_code, 200)

        # Verify execute_summarize_session_group was called with None extra_context
        mock_execute.assert_called_once_with(
            session_ids=["session1", "session2"],
            user_id=self.user.pk,
            team=self.team,
            min_timestamp=datetime(2024, 1, 1, 10, 0, 0),
            max_timestamp=datetime(2024, 1, 1, 11, 0, 0),
            extra_summary_context=None,
            local_reads_prod=False,
        )

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    def test_create_summaries_missing_session_ids(self, mock_feature_enabled: Mock) -> None:
        """Test validation error when session_ids is missing"""
        mock_feature_enabled.return_value = True

        response = self.client.post(
            self.url,
            {"focus_area": "test"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertEqual(error["attr"], "session_ids")

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    def test_create_summaries_empty_session_ids(self, mock_feature_enabled: Mock) -> None:
        """Test validation error when session_ids is empty"""
        mock_feature_enabled.return_value = True

        response = self._make_api_request(session_ids=[])

        self.assertEqual(response.status_code, 400)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertEqual(error["attr"], "session_ids")

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    def test_create_summaries_too_many_session_ids(self, mock_feature_enabled: Mock) -> None:
        """Test validation error when too many session_ids provided"""
        mock_feature_enabled.return_value = True
        session_ids: list[str] = [f"session{i}" for i in range(303)]  # More than max of 300

        response = self._make_api_request(session_ids=session_ids)

        self.assertEqual(response.status_code, 400)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertEqual(error["attr"], "session_ids")

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    def test_create_summaries_focus_area_too_long(self, mock_feature_enabled: Mock) -> None:
        """Test validation error when focus_area is too long"""
        mock_feature_enabled.return_value = True
        long_focus_area: str = "x" * 501  # More than max of 500

        response = self._make_api_request(session_ids=["session1"], focus_area=long_focus_area)

        self.assertEqual(response.status_code, 400)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertEqual(error["attr"], "focus_area")

    def test_create_summaries_unauthenticated(self) -> None:
        """Test that unauthenticated requests are rejected"""
        self.client.logout()

        response = self._make_api_request(session_ids=["session1"])

        self.assertEqual(response.status_code, 401)

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    def test_create_summaries_feature_disabled(self, mock_feature_enabled: Mock) -> None:
        """Test error when ai-session-summary feature is disabled"""
        mock_feature_enabled.return_value = False

        response = self._make_api_request(session_ids=["session1"])

        self.assertEqual(response.status_code, 400)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertIn("Session summaries are not enabled", str(error))

    @patch("ee.api.session_summaries.is_cloud")
    def test_create_summaries_not_cloud(self, mock_is_cloud: Mock) -> None:
        """Test error when not in cloud environment"""
        mock_is_cloud.return_value = False

        response = self._make_api_request(session_ids=["session1"])

        self.assertEqual(response.status_code, 400)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertIn("Session summaries are only supported in PostHog Cloud", str(error))

    @patch.dict(os.environ, {}, clear=True)  # Remove OPENAI_API_KEY
    def test_create_summaries_no_openai_key(self) -> None:
        """Test error when OPENAI_API_KEY is not set"""
        response = self._make_api_request(session_ids=["session1"])

        self.assertEqual(response.status_code, 400)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertIn("Session summaries are only supported in PostHog Cloud", str(error))

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.SessionReplayEvents")
    def test_create_summaries_session_not_found(self, mock_replay_events: Mock, mock_feature_enabled: Mock) -> None:
        """Test error when session doesn't exist or doesn't belong to team"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_replay_events.return_value = self._create_mock_replay_events(
            sessions_found=set()  # Empty set means no sessions found
        )

        response = self._make_api_request(session_ids=["nonexistent_session"])

        self.assertEqual(response.status_code, 400)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertIn("Sessions not found or do not belong to this team: nonexistent_session", str(error))

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.SessionReplayEvents")
    def test_create_summaries_mixed_session_existence(
        self, mock_replay_events: Mock, mock_feature_enabled: Mock
    ) -> None:
        """Test error when some sessions exist and some don't"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_replay_events.return_value = self._create_mock_replay_events(
            sessions_found={"session1"},  # Only session1 found
            min_timestamp=datetime(2024, 1, 1, 10, 0, 0),
            max_timestamp=datetime(2024, 1, 1, 11, 0, 0),
        )

        response = self._make_api_request(session_ids=["session1", "session2"])

        self.assertEqual(response.status_code, 400)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertIn("Sessions not found or do not belong to this team: session2", str(error))

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.SessionReplayEvents")
    @patch("ee.api.session_summaries.execute_summarize_session_group")
    @patch("ee.api.session_summaries.create_summary_notebook")
    def test_create_summaries_execution_failure(
        self, mock_create_notebook: Mock, mock_execute: Mock, mock_replay_events: Mock, mock_feature_enabled: Mock
    ) -> None:
        """Test handling of execution failures"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_replay_events.return_value = self._create_mock_replay_events(
            sessions_found={"session1"},
            min_timestamp=datetime(2024, 1, 1, 10, 0, 0),
            max_timestamp=datetime(2024, 1, 1, 11, 0, 0),
        )

        # Mock execution failure
        mock_execute.side_effect = Exception("Workflow execution failed")

        response = self._make_api_request(session_ids=["session1"])

        self.assertEqual(response.status_code, 500)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertIn("Failed to generate session summaries", str(error))

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.SessionReplayEvents")
    @patch("ee.api.session_summaries.execute_summarize_session_group")
    def test_create_summaries_validates_all_sessions_before_execution(
        self, mock_execute: Mock, mock_replay_events: Mock, mock_feature_enabled: Mock
    ) -> None:
        """Test that all sessions are validated before execution starts"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_replay_events.return_value = self._create_mock_replay_events(
            sessions_found={"session1", "session2"},  # session3 not found
            min_timestamp=datetime(2024, 1, 1, 10, 0, 0),
            max_timestamp=datetime(2024, 1, 1, 11, 0, 0),
        )

        response = self._make_api_request(session_ids=["session1", "session2", "session3"])

        self.assertEqual(response.status_code, 400)
        # Execution should never be called due to validation failure
        mock_execute.assert_not_called()

    def test_wrong_http_method(self) -> None:
        """Test that only POST is allowed"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)  # Method Not Allowed

        response = self.client.put(self.url, {})
        self.assertEqual(response.status_code, 405)

        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 405)

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.SessionReplayEvents")
    @patch("ee.api.session_summaries.execute_summarize_session_group")
    @patch("ee.api.session_summaries.create_summary_notebook")
    def test_create_summaries_single_session(
        self, mock_create_notebook: Mock, mock_execute: Mock, mock_replay_events: Mock, mock_feature_enabled: Mock
    ) -> None:
        """Test that single session works correctly"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_replay_events.return_value = self._create_mock_replay_events(
            sessions_found={"single_session"},
            min_timestamp=datetime(2024, 1, 1, 10, 0, 0),
            max_timestamp=datetime(2024, 1, 1, 11, 0, 0),
        )

        mock_result = self.create_mock_result()
        mock_execute.return_value = mock_result

        response = self._make_api_request(session_ids=["single_session"])

        self.assertEqual(response.status_code, 200)

        # Verify session validation was called once
        mock_replay_events.return_value.sessions_found_with_timestamps.assert_called_once_with(
            ["single_session"], self.team
        )
