import os
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Optional, Union

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.http import HttpResponse

from rest_framework import exceptions

from posthog.temporal.session_replay.session_summary_group.types import SessionSummaryStreamUpdate

from ee.hogai.session_summaries.session.output_data import SessionSummarySerializer
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
    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session_group")
    def test_create_summaries_success(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
        mock_capture_started: Mock,
        mock_capture_generated: Mock,
    ) -> None:
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
        mock_capture_generated.assert_called_once()
        generated_kwargs = mock_capture_generated.call_args[1]
        self.assertEqual(generated_kwargs["summary_source"], "api")
        self.assertEqual(generated_kwargs["summary_type"], "group")
        self.assertEqual(generated_kwargs["session_ids"], ["session1", "session2"])
        self.assertTrue(generated_kwargs["success"])
        self.assertIsNone(generated_kwargs.get("error_type"))
        # Tracking IDs should match
        self.assertEqual(started_kwargs["tracking_id"], generated_kwargs["tracking_id"])

    def test_create_summaries_missing_session_ids(self) -> None:
        response = self.client.post(
            self.url,
            {"focus_area": "test"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error: dict[str, Any] = response.json()
        self.assertEqual(error["attr"], "session_ids")

    def test_create_summaries_empty_session_ids(self) -> None:
        response = self._make_api_request(session_ids=[])

        self.assertEqual(response.status_code, 400)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertEqual(error["attr"], "session_ids")

    def test_create_summaries_too_many_session_ids(self) -> None:
        session_ids: list[str] = [f"session{i}" for i in range(303)]  # More than max of 300

        response = self._make_api_request(session_ids=session_ids)

        self.assertEqual(response.status_code, 400)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertEqual(error["attr"], "session_ids")

    def test_create_summaries_focus_area_too_long(self) -> None:
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

    @patch("ee.api.session_summaries.find_sessions_timestamps")
    def test_create_summaries_session_not_found(self, mock_find_sessions: Mock) -> None:
        # Mock find_sessions_timestamps to raise validation error for not found sessions
        mock_find_sessions.side_effect = exceptions.ValidationError(
            "Sessions not found or do not belong to this team: nonexistent_session"
        )

        response = self._make_api_request(session_ids=["nonexistent_session"])

        self.assertEqual(response.status_code, 400)
        error: dict[str, Any] = response.json()  # type: ignore[attr-defined]
        self.assertIn("Sessions not found or do not belong to this team: nonexistent_session", str(error))

    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session_group")
    def test_create_summaries_execution_failure(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
    ) -> None:
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

    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session")
    def test_create_summaries_individually_success(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
    ) -> None:
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

    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session")
    def test_create_summaries_individually_partial_failure(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
    ) -> None:
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


MOCK_SUMMARY_DATA: dict[str, Any] = {
    "segments": [
        {
            "index": 0,
            "name": "Login",
            "start_event_id": "evt00001",
            "end_event_id": "evt00002",
            "meta": {
                "duration": 30,
                "duration_percentage": 1.0,
                "events_count": 2,
                "events_percentage": 1.0,
                "key_action_count": 1,
                "failure_count": 0,
                "abandonment_count": 0,
                "confusion_count": 0,
                "exception_count": 0,
            },
        }
    ],
    "key_actions": [
        {
            "segment_index": 0,
            "events": [
                {
                    "description": "Clicked login",
                    "abandonment": False,
                    "confusion": False,
                    "exception": None,
                    "event_id": "evt00001",
                    "timestamp": "2024-01-01T10:00:00Z",
                    "milliseconds_since_start": 0,
                    "window_id": "w1",
                    "current_url": "https://app.example.com/login",
                    "event": "$autocapture",
                    "event_type": "click",
                    "event_index": 0,
                    "session_id": "session1",
                    "event_uuid": "00000000-0000-0000-0000-000000000001",
                }
            ],
        }
    ],
    "segment_outcomes": [{"segment_index": 0, "summary": "User logged in successfully", "success": True}],
    "session_outcome": {"description": "Successful login", "success": True},
    "sentiment": {"frustration_score": 0.1, "outcome": "successful", "sentiment_signals": []},
}


def _parse_sse_events(content: bytes) -> list[dict[str, str]]:
    """Parse SSE response bytes into a list of dicts with 'event' and 'data' keys."""
    raw_blocks = content.decode().split("\n\n")
    events = []
    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue
        parsed: dict[str, str] = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                parsed["event"] = line[len("event:") :].strip()
            elif line.startswith("data:"):
                parsed["data"] = line[len("data:") :].strip()
        if parsed:
            events.append(parsed)
    return events


class TestStreamSessionSummariesAPI(APIBaseTest):
    environment_patches: list[Any]

    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/environments/{self.team.id}/session_summaries/stream_batch/"

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

    def _make_streaming_request(self, session_ids: list[str], focus_area: Optional[str] = None) -> Any:
        payload: dict[str, Any] = {"session_ids": session_ids}
        if focus_area is not None:
            payload["focus_area"] = focus_area
        return self.client.post(self.url, payload, format="json")

    def _get_sse_events(self, response: Any) -> list[dict[str, str]]:
        content = b"".join(response.streaming_content)
        return _parse_sse_events(content)

    def _make_valid_summary_serializer(self, session_id: str = "session1") -> SessionSummarySerializer:
        data = {
            **MOCK_SUMMARY_DATA,
            "key_actions": [
                {
                    **MOCK_SUMMARY_DATA["key_actions"][0],
                    "events": [{**MOCK_SUMMARY_DATA["key_actions"][0]["events"][0], "session_id": session_id}],
                }
            ],
        }
        serializer = SessionSummarySerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer

    @patch("ee.api.session_summaries.capture_session_summary_generated")
    @patch("ee.api.session_summaries.capture_session_summary_started")
    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session")
    def test_stream_individually_success_emits_summary_and_done_events(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
        mock_capture_started: Mock,
        mock_capture_generated: Mock,
    ) -> None:
        mock_find_sessions.return_value = (
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )
        mock_execute.side_effect = lambda session_id, **kwargs: get_mock_enriched_llm_json_response(session_id)

        response = self._make_streaming_request(session_ids=["session_1"])

        self.assertEqual(response.status_code, 200)
        events = self._get_sse_events(response)

        event_types = [e["event"] for e in events]
        self.assertIn("summary", event_types)
        self.assertIn("done", event_types)

        summary_event = next(e for e in events if e["event"] == "summary")
        summary_data = json.loads(summary_event["data"])
        self.assertEqual(summary_data["session_id"], "session_1")
        self.assertIn("summary", summary_data)
        self.assertIn("segments", summary_data["summary"])
        self.assertIn("key_actions", summary_data["summary"])
        self.assertIn("segment_outcomes", summary_data["summary"])
        self.assertIn("session_outcome", summary_data["summary"])

        done_event = next(e for e in events if e["event"] == "done")
        done_data = json.loads(done_event["data"])
        self.assertIn("session_1", done_data["completed"])
        self.assertEqual(done_data["failed"], [])

    @patch("ee.api.session_summaries.capture_session_summary_generated")
    @patch("ee.api.session_summaries.capture_session_summary_started")
    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session")
    def test_stream_individually_mixed_success_and_failure_emits_both_event_types(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
        mock_capture_started: Mock,
        mock_capture_generated: Mock,
    ) -> None:
        mock_find_sessions.return_value = (
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )

        def side_effect(session_id: str, **kwargs: Any) -> Any:
            if session_id == "session_ok":
                return get_mock_enriched_llm_json_response(session_id)
            raise Exception("summarization failed")

        mock_execute.side_effect = side_effect

        response = self._make_streaming_request(session_ids=["session_ok", "session_fail"])

        self.assertEqual(response.status_code, 200)
        events = self._get_sse_events(response)
        event_types = [e["event"] for e in events]

        self.assertIn("summary", event_types)
        self.assertIn("error", event_types)
        self.assertIn("done", event_types)

        summary_event = next(e for e in events if e["event"] == "summary")
        summary_data = json.loads(summary_event["data"])
        self.assertEqual(summary_data["session_id"], "session_ok")

        error_event = next(e for e in events if e["event"] == "error")
        error_data = json.loads(error_event["data"])
        self.assertEqual(error_data["session_id"], "session_fail")
        self.assertIn("error", error_data)
        self.assertIsInstance(error_data["error"], str)

        done_event = next(e for e in events if e["event"] == "done")
        done_data = json.loads(done_event["data"])
        self.assertIn("session_ok", done_data["completed"])
        self.assertIn("session_fail", done_data["failed"])

    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session")
    def test_stream_individually_response_headers(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
    ) -> None:
        mock_find_sessions.return_value = (
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )
        mock_execute.side_effect = lambda session_id, **kwargs: get_mock_enriched_llm_json_response(session_id)

        response = self._make_streaming_request(session_ids=["session_1"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get("Content-Type"), "text/event-stream")
        self.assertEqual(response.get("Cache-Control"), "no-cache")
        self.assertEqual(response.get("X-Accel-Buffering"), "no")

    @patch("ee.api.session_summaries.capture_session_summary_generated")
    @patch("ee.api.session_summaries.capture_session_summary_started")
    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session")
    def test_stream_individually_tracking_uses_single_stream_summary_type(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
        mock_capture_started: Mock,
        mock_capture_generated: Mock,
    ) -> None:
        mock_find_sessions.return_value = (
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )
        mock_execute.side_effect = lambda session_id, **kwargs: get_mock_enriched_llm_json_response(session_id)

        response = self._make_streaming_request(session_ids=["session_1", "session_2"])
        # Consume the streaming content to trigger the generator
        b"".join(response.streaming_content)

        mock_capture_started.assert_called_once()
        started_kwargs = mock_capture_started.call_args[1]
        self.assertEqual(started_kwargs["summary_type"], "single")
        self.assertEqual(started_kwargs["summary_source"], "api")
        self.assertEqual(started_kwargs["session_ids"], ["session_1", "session_2"])

        mock_capture_generated.assert_called_once()
        generated_kwargs = mock_capture_generated.call_args[1]
        self.assertEqual(generated_kwargs["summary_type"], "single")
        self.assertEqual(generated_kwargs["summary_source"], "api")
        self.assertEqual(generated_kwargs["session_ids"], ["session_1", "session_2"])

        self.assertEqual(started_kwargs["tracking_id"], generated_kwargs["tracking_id"])

    @patch("ee.api.session_summaries.capture_session_summary_generated")
    @patch("ee.api.session_summaries.capture_session_summary_started")
    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session")
    def test_stream_individually_done_event_reflects_success_and_failure_lists(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
        mock_capture_started: Mock,
        mock_capture_generated: Mock,
    ) -> None:
        mock_find_sessions.return_value = (
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )
        mock_execute.side_effect = lambda session_id, **kwargs: get_mock_enriched_llm_json_response(session_id)

        response = self._make_streaming_request(session_ids=["s1", "s2", "s3"])
        events = self._get_sse_events(response)

        done_event = next(e for e in events if e["event"] == "done")
        done_data = json.loads(done_event["data"])

        self.assertCountEqual(done_data["completed"], ["s1", "s2", "s3"])
        self.assertEqual(done_data["failed"], [])

    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session")
    def test_stream_individually_all_failures_produces_only_error_and_done_events(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
    ) -> None:
        mock_find_sessions.return_value = (
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )
        mock_execute.side_effect = Exception("summarization failed")

        response = self._make_streaming_request(session_ids=["session_1", "session_2"])

        self.assertEqual(response.status_code, 200)
        events = self._get_sse_events(response)
        event_types = [e["event"] for e in events]

        self.assertNotIn("summary", event_types)
        self.assertIn("error", event_types)
        self.assertIn("done", event_types)

        done_event = next(e for e in events if e["event"] == "done")
        done_data = json.loads(done_event["data"])
        self.assertEqual(done_data["completed"], [])
        self.assertCountEqual(done_data["failed"], ["session_1", "session_2"])

    def test_stream_individually_missing_session_ids_returns_400(self) -> None:
        # Input validation happens before streaming begins, so the response is a regular 400
        response = self.client.post(self.url, {"focus_area": "login"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_stream_individually_empty_session_ids_returns_400(self) -> None:
        response = self._make_streaming_request(session_ids=[])
        self.assertEqual(response.status_code, 400)

    def test_stream_individually_unauthenticated_returns_401(self) -> None:
        self.client.logout()
        response = self._make_streaming_request(session_ids=["session_1"])
        self.assertEqual(response.status_code, 401)

    @patch("ee.api.session_summaries.is_cloud")
    def test_stream_individually_not_cloud_returns_400(self, mock_is_cloud: Mock) -> None:
        mock_is_cloud.return_value = False
        response = self._make_streaming_request(session_ids=["session_1"])
        self.assertEqual(response.status_code, 400)

    @patch("ee.api.session_summaries.find_sessions_timestamps")
    def test_stream_individually_session_not_found_returns_400(self, mock_find_sessions: Mock) -> None:
        mock_find_sessions.side_effect = exceptions.ValidationError(
            "Sessions not found or do not belong to this team: nonexistent"
        )
        response = self._make_streaming_request(session_ids=["nonexistent"])
        self.assertEqual(response.status_code, 400)

    @patch("ee.api.session_summaries.capture_session_summary_generated")
    @patch("ee.api.session_summaries.capture_session_summary_started")
    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session")
    def test_stream_individually_with_focus_area_passes_extra_context(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
        mock_capture_started: Mock,
        mock_capture_generated: Mock,
    ) -> None:
        mock_find_sessions.return_value = (
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )
        mock_execute.side_effect = lambda session_id, **kwargs: get_mock_enriched_llm_json_response(session_id)

        response = self._make_streaming_request(session_ids=["session_1"], focus_area="checkout flow")
        events = self._get_sse_events(response)

        event_types = [e["event"] for e in events]
        self.assertIn("summary", event_types)
        self.assertIn("done", event_types)

        # The extra_summary_context should flow through to execute_summarize_session
        call_kwargs = mock_execute.call_args[1]
        self.assertIsNotNone(call_kwargs.get("extra_summary_context"))
        self.assertEqual(call_kwargs["extra_summary_context"].focus_area, "checkout flow")

    @patch("ee.api.session_summaries.capture_session_summary_generated")
    @patch("ee.api.session_summaries.capture_session_summary_started")
    @patch("ee.api.session_summaries.find_sessions_timestamps")
    @patch("ee.api.session_summaries.execute_summarize_session")
    def test_stream_individually_tracking_generated_success_false_when_all_fail(
        self,
        mock_execute: Mock,
        mock_find_sessions: Mock,
        mock_capture_started: Mock,
        mock_capture_generated: Mock,
    ) -> None:
        mock_find_sessions.return_value = (
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )
        mock_execute.side_effect = Exception("summarization failed")

        response = self._make_streaming_request(session_ids=["session_1"])
        b"".join(response.streaming_content)

        mock_capture_generated.assert_called_once()
        generated_kwargs = mock_capture_generated.call_args[1]
        self.assertFalse(generated_kwargs["success"])
