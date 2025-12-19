import os
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Optional, Union

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.http import HttpResponse

from rest_framework import exceptions

from posthog.temporal.ai.session_summary.types.group import SessionSummaryStreamUpdate

from ee.hogai.session_summaries.session_group.patterns import (
    EnrichedSessionGroupSummaryPattern,
    EnrichedSessionGroupSummaryPatternsList,
    EnrichedSessionGroupSummaryPatternStats,
)
from ee.hogai.session_summaries.tests.conftest import get_mock_enriched_llm_json_response


class TestSessionSummariesAPI(APIBaseTest):
    url: str
    environment_patches: list[Any]

    async def _create_async_generator(
        self, result: tuple[EnrichedSessionGroupSummaryPatternsList, str]
    ) -> AsyncIterator[
        tuple[SessionSummaryStreamUpdate, Union[str, tuple[EnrichedSessionGroupSummaryPatternsList, str]]]
    ]:
        """Helper to create an async generator that yields progress updates and final result."""
        # Yield progress updates in the new tuple format
        yield (
            SessionSummaryStreamUpdate.UI_STATUS,
            "Starting session group summarization...",
        )
        yield (SessionSummaryStreamUpdate.UI_STATUS, "Processing sessions...")
        yield (SessionSummaryStreamUpdate.UI_STATUS, "Finding patterns...")
        # Yield final result
        yield (SessionSummaryStreamUpdate.FINAL_RESULT, result)

    def _make_api_request(self, session_ids: list[str], focus_area: Optional[str] = None) -> HttpResponse:
        """Helper to make API requests with consistent formatting."""
        payload: dict[str, Union[list[str], str]] = {"session_ids": session_ids}
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

    def create_mock_result(self) -> EnrichedSessionGroupSummaryPatternsList:
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

    @patch("ee.api.session_summaries.capture_session_summary_generated")
    @patch("ee.api.session_summaries.capture_session_summary_started")
    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session_group")
    def test_create_summaries_success(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
        mock_feature_enabled: Mock,
        mock_capture_started: Mock,
        mock_capture_generated: Mock,
    ) -> None:
        """Test successful creation of session summaries"""
        # Setup mocks
        mock_feature_enabled.side_effect = [True, False, False]  # Allow summaries, but not video validation (2 checks)
        mock_find_sessions.return_value = (
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )
        mock_result = self.create_mock_result()
        mock_execute.return_value = self._create_async_generator((mock_result, "session-group-summary-id"))
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
            user=self.user,
            team=self.team,
            min_timestamp=datetime(2024, 1, 1, 10, 0, 0),
            max_timestamp=datetime(2024, 1, 1, 11, 0, 0),
            extra_summary_context=mock_execute.call_args[1]["extra_summary_context"],
            video_validation_enabled=False,
            summary_title="Group summary",
        )
        # Check extra_summary_context separately
        self.assertEqual(mock_execute.call_args[1]["extra_summary_context"].focus_area, "login process")
        # Verify tracking was called
        mock_capture_started.assert_called_once()
        started_kwargs = mock_capture_started.call_args[1]
        self.assertEqual(started_kwargs["summary_source"], "api")
        self.assertEqual(started_kwargs["summary_type"], "group")
        self.assertEqual(started_kwargs["session_ids"], ["session1", "session2"])
        self.assertFalse(started_kwargs["is_streaming"])
        mock_capture_generated.assert_called_once()
        generated_kwargs = mock_capture_generated.call_args[1]
        self.assertEqual(generated_kwargs["summary_source"], "api")
        self.assertEqual(generated_kwargs["summary_type"], "group")
        self.assertEqual(generated_kwargs["session_ids"], ["session1", "session2"])
        self.assertTrue(generated_kwargs["success"])
        self.assertIsNone(generated_kwargs.get("error_type"))
        # Tracking IDs should match
        self.assertEqual(started_kwargs["tracking_id"], generated_kwargs["tracking_id"])

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
        error: dict[str, Any] = response.json()
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
    @patch("ee.api.session_summaries.find_sessions_timestamps")
    def test_create_summaries_session_not_found(self, mock_find_sessions: Mock, mock_feature_enabled: Mock) -> None:
        """Test error when session doesn't exist or doesn't belong to team"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        # Mock find_sessions_timestamps to raise validation error for not found sessions
        mock_find_sessions.side_effect = exceptions.ValidationError(
            "Sessions not found or do not belong to this team: nonexistent_session"
        )

        response = self._make_api_request(session_ids=["nonexistent_session"])

        self.assertEqual(response.status_code, 400)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertIn("Sessions not found or do not belong to this team: nonexistent_session", str(error))

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session_group")
    def test_create_summaries_execution_failure(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
        mock_feature_enabled: Mock,
    ) -> None:
        """Test handling of execution failures"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_find_sessions.return_value = (
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )

        # Mock execution failure - create async generator that raises exception
        async def failing_generator():
            yield (SessionSummaryStreamUpdate.UI_STATUS, "Starting...")
            raise Exception("Workflow execution failed")

        mock_execute.return_value = failing_generator()

        response = self._make_api_request(session_ids=["session1"])

        self.assertEqual(response.status_code, 500)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertIn("Failed to generate session summaries", str(error))

    def test_wrong_http_method(self) -> None:
        """Test that only POST is allowed"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)  # Method Not Allowed

        response = self.client.put(self.url, {})
        self.assertEqual(response.status_code, 405)

        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 405)

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session")
    def test_create_summaries_individually_success(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
        mock_feature_enabled: Mock,
    ) -> None:
        """Test successful creation of individual session summaries"""
        mock_feature_enabled.return_value = True
        mock_find_sessions.return_value = (
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )
        mock_execute.side_effect = lambda session_id, **kwargs: get_mock_enriched_llm_json_response(session_id)
        # Make request
        url = f"/api/environments/{self.team.id}/session_summaries/create_session_summaries_individually/"
        response = self.client.post(url, {"session_ids": ["session_1", "session_2"]}, format="json")
        # Check the response - should return two summaries
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data.keys()), {"session_1", "session_2"})
        for session_id in ["session_1", "session_2"]:
            self.assertIn("segments", data[session_id])
            self.assertIn("key_actions", data[session_id])
            self.assertIn("segment_outcomes", data[session_id])
            self.assertIn("session_outcome", data[session_id])

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session")
    def test_create_summaries_individually_partial_failure(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
        mock_feature_enabled: Mock,
    ) -> None:
        """Test that partial failures return only successful summaries"""
        mock_feature_enabled.return_value = True
        mock_find_sessions.return_value = (
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )

        # Mock execute to succeed for first session, fail for second
        def mock_execute_side_effect(session_id: str, **kwargs: Any) -> dict[str, Any]:
            if session_id == "session_1":
                return get_mock_enriched_llm_json_response(session_id)
            raise Exception("Failed to summarize session")

        mock_execute.side_effect = mock_execute_side_effect

        # Make request
        url = f"/api/environments/{self.team.id}/session_summaries/create_session_summaries_individually/"
        response = self.client.post(url, {"session_ids": ["session_1", "session_2"]}, format="json")
        # Check the response - should return one summary
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data.keys()), {"session_1"})
        self.assertIn("segments", data["session_1"])
        self.assertIn("key_actions", data["session_1"])
        self.assertIn("segment_outcomes", data["session_1"])
        self.assertIn("session_outcome", data["session_1"])
