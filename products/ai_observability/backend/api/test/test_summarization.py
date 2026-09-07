"""
Tests for summarization API endpoint.

Tests cover title field presence, request validation, and response format.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events

from products.ai_observability.backend.summarization.llm.schema import (
    InterestingNote,
    SummarizationResponse,
    SummaryBullet,
)

TEST_TEXT_REPR_BUDGET = 4000


def _oversized_payload(summarize_type: str, one_long_line: bool) -> dict[str, Any]:
    # A single long line cannot be sampled line-wise, which is the shape that escapes a naive bound.
    ai_input: Any = (
        "x" * (TEST_TEXT_REPR_BUDGET * 4)
        if one_long_line
        else [{"role": "user", "content": f"turn {i} " + "detail " * 40} for i in range(200)]
    )
    event = {
        "id": "gen-oversized",
        "event": "$ai_generation",
        "properties": {"$ai_input": ai_input},
    }
    if summarize_type == "event":
        return {"event": event}
    return {
        "trace": {"id": "trace-oversized", "properties": {"$ai_span_name": "oversized"}},
        "hierarchy": [{"event": event, "children": []}],
    }


class TestSummarizationAPI(APIBaseTest):
    """Test summarization API endpoints."""

    def test_unauthenticated_user_cannot_access_summarization(self):
        """Should require authentication to access summarization endpoints."""
        self.client.logout()
        response = self.client.post(f"/api/environments/{self.team.id}/llm_analytics/summarization/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("products.ai_observability.backend.api.summarization.summarize")
    def test_event_summarization_includes_title(self, mock_summarize):
        """Should include title field in summarization response."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        # Mock the summarize function to return a SummarizationResponse with title
        mock_summary = SummarizationResponse(
            title="Test Event Summary",
            flow_diagram="User Input\n    |\nLLM Processing\n    |\nResponse",
            summary_bullets=[
                SummaryBullet(text="User sent a test message", line_refs="L1"),
                SummaryBullet(text="LLM processed the request", line_refs="L5"),
                SummaryBullet(text="Response generated successfully", line_refs="L10"),
            ],
            interesting_notes=[
                InterestingNote(text="Clean execution with no errors", line_refs=""),
            ],
        )

        mock_summarize.return_value = mock_summary

        request_data = {
            "summarize_type": "event",
            "mode": "minimal",
            "data": {
                "event": {
                    "id": "gen123",
                    "event": "$ai_generation",
                    "properties": {
                        "$ai_input": [{"role": "user", "content": "Test"}],
                        "$ai_output_choices": [{"message": {"role": "assistant", "content": "Response"}}],
                    },
                }
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        # Verify response structure
        self.assertIn("summary", data)
        self.assertIn("text_repr", data)
        self.assertIn("metadata", data)

        # Verify title field is present in summary
        self.assertIn("title", data["summary"])
        self.assertEqual(data["summary"]["title"], "Test Event Summary")

        # Verify other expected fields
        self.assertIn("flow_diagram", data["summary"])
        self.assertIn("summary_bullets", data["summary"])
        self.assertIn("interesting_notes", data["summary"])

    @patch("products.ai_observability.backend.api.summarization.summarize")
    def test_trace_summarization_includes_title(self, mock_summarize):
        """Should include title field in trace summarization response."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        # Mock the summarize function
        mock_summary = SummarizationResponse(
            title="Multi-step Trace Execution",
            flow_diagram="Start\n    |\nProcess\n    |\nComplete",
            summary_bullets=[
                SummaryBullet(text="Trace started", line_refs="L1"),
                SummaryBullet(text="Multiple steps executed", line_refs="L15"),
            ],
            interesting_notes=[],
        )

        mock_summarize.return_value = mock_summary

        request_data = {
            "summarize_type": "trace",
            "mode": "detailed",
            "data": {
                "trace": {
                    "id": "trace123",
                    "properties": {"$ai_span_name": "test-trace"},
                },
                "hierarchy": [
                    {
                        "event": {
                            "id": "gen1",
                            "event": "$ai_generation",
                            "properties": {"$ai_span_name": "generation"},
                        },
                        "children": [],
                    }
                ],
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        # Verify title is present
        self.assertIn("title", data["summary"])
        self.assertEqual(data["summary"]["title"], "Multi-step Trace Execution")

    @parameterized.expand(
        [
            ("event_many_lines", "event", False),
            ("event_one_long_line", "event", True),
            ("trace_many_lines", "trace", False),
            ("trace_one_long_line", "trace", True),
        ]
    )
    @patch(
        "products.ai_observability.backend.api.summarization.text_repr_budget",
        return_value=TEST_TEXT_REPR_BUDGET,
    )
    @patch("products.ai_observability.backend.api.summarization.summarize")
    def test_oversized_entity_is_bounded_before_the_model_call(
        self, _name, summarize_type, one_long_line, mock_summarize, _mock_budget
    ):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_summarize.return_value = SummarizationResponse(
            title="Bounded",
            flow_diagram="Start",
            summary_bullets=[SummaryBullet(text="Bounded", line_refs="L1")],
            interesting_notes=[],
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            {
                "summarize_type": summarize_type,
                "mode": "minimal",
                "force_refresh": True,
                "data": _oversized_payload(summarize_type, one_long_line),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        text_repr = mock_summarize.call_args.kwargs["text_repr"]
        self.assertLessEqual(len(text_repr), TEST_TEXT_REPR_BUDGET)

    def test_missing_summarize_type(self):
        """Should return 400 for missing summarize_type."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        request_data: dict[str, Any] = {"data": {"event": {}}}

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("summarize_type", str(response.data).lower())

    def test_missing_data(self):
        """Should return 400 for missing data."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        request_data = {"summarize_type": "event"}

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("data", str(response.data).lower())

    def test_invalid_summarize_type(self):
        """Should return 400 for invalid summarize_type."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        request_data = {
            "summarize_type": "invalid",
            "data": {"event": {}},
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.ai_observability.backend.api.summarization.summarize")
    def test_events_in_same_trace_have_separate_cache(self, mock_summarize):
        """Should cache event summaries by event ID, not trace ID, to avoid collisions."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        # Mock the summarize function to return different summaries
        def mock_summarize_fn(*args, **kwargs):
            # Return different title based on which event we're summarizing
            text = kwargs.get("text_repr", "")
            if "Event A" in text:
                return SummarizationResponse(
                    title="Event A Summary",
                    flow_diagram="A Flow",
                    summary_bullets=[SummaryBullet(text="Event A action", line_refs="L1")],
                    interesting_notes=[],
                )
            else:
                return SummarizationResponse(
                    title="Event B Summary",
                    flow_diagram="B Flow",
                    summary_bullets=[SummaryBullet(text="Event B action", line_refs="L1")],
                    interesting_notes=[],
                )

        mock_summarize.side_effect = mock_summarize_fn

        # Create two events in the same trace with different IDs
        trace_id = "trace_123"
        event_a_request = {
            "summarize_type": "event",
            "mode": "minimal",
            "data": {
                "event": {
                    "id": "event_a",
                    "event": "$ai_generation",
                    "properties": {
                        "$ai_trace_id": trace_id,
                        "$ai_input": [{"role": "user", "content": "Event A"}],
                    },
                }
            },
        }

        event_b_request = {
            "summarize_type": "event",
            "mode": "minimal",
            "data": {
                "event": {
                    "id": "event_b",
                    "event": "$ai_generation",
                    "properties": {
                        "$ai_trace_id": trace_id,  # Same trace ID
                        "$ai_input": [{"role": "user", "content": "Event B"}],
                    },
                }
            },
        }

        # Summarize event A
        response_a = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            event_a_request,
            format="json",
        )
        self.assertEqual(response_a.status_code, status.HTTP_200_OK)
        self.assertEqual(response_a.data["summary"]["title"], "Event A Summary")

        # Summarize event B - should get a different summary, not event A's cached result
        response_b = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            event_b_request,
            format="json",
        )
        self.assertEqual(response_b.status_code, status.HTTP_200_OK)
        self.assertEqual(response_b.data["summary"]["title"], "Event B Summary")

        # Verify they're different
        self.assertNotEqual(response_a.data["summary"]["title"], response_b.data["summary"]["title"])

    def test_batch_check_unauthenticated(self):
        """Should require authentication to access batch_check endpoint."""
        self.client.logout()
        response = self.client.post(f"/api/environments/{self.team.id}/llm_analytics/summarization/batch_check/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_batch_check_empty_traces(self):
        """Should return empty list when no traces have cached summaries."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/batch_check/",
            {"trace_ids": ["trace1", "trace2"], "mode": "minimal"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["summaries"], [])

    @patch("products.ai_observability.backend.api.summarization.summarize")
    def test_batch_check_returns_cached_summaries(self, mock_summarize):
        """Should return cached summaries for traces that have been summarized."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        mock_summary = SummarizationResponse(
            title="Cached Summary",
            flow_diagram="Flow",
            summary_bullets=[SummaryBullet(text="Step", line_refs="L1")],
            interesting_notes=[],
        )
        mock_summarize.return_value = mock_summary

        # First, summarize a trace to populate the cache
        summarize_request = {
            "summarize_type": "trace",
            "mode": "minimal",
            "data": {
                "trace": {"id": "cached_trace", "properties": {"$ai_span_name": "test"}},
                "hierarchy": [],
            },
        }
        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            summarize_request,
            format="json",
        )

        # Now check batch - should return the cached summary
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/batch_check/",
            {"trace_ids": ["cached_trace", "not_cached"], "mode": "minimal"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["summaries"]), 1)
        self.assertEqual(response.data["summaries"][0]["trace_id"], "cached_trace")
        self.assertEqual(response.data["summaries"][0]["title"], "Cached Summary")

    def test_batch_check_requires_trace_ids(self):
        """Should return 400 when trace_ids is missing."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/batch_check/",
            {"mode": "minimal"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("trace_ids", str(response.data).lower())

    def test_summarization_denied_when_ai_consent_not_approved(self):
        """Should return 403 when AI data processing is not approved."""
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            {"summarize_type": "event", "mode": "minimal", "data": {"event": {"id": "test"}}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("AI data processing must be approved", response.data["detail"])


class TestSummarizationByID(ClickhouseTestMixin, APIBaseTest):
    def _approve_ai_processing(self) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def _ingest_ai_event(self, event: str, event_uuid: uuid.UUID, timestamp: datetime, metadata: dict, content: dict):
        """Write an event the way ingestion does: metadata on `events`, message content only on `ai_events`.

        Writes both tables directly rather than going through `flush_persons_and_events`, which
        would mirror the stripped events row into ai_events and hide the split being tested.
        """
        row = {
            "event": event,
            "team": self.team,
            "distinct_id": "user-1",
            "timestamp": timestamp,
            "event_uuid": str(event_uuid),
        }
        bulk_create_events([{**row, "properties": metadata}])
        bulk_create_ai_events([{**row, "properties": {**metadata, **content}}])

    @parameterized.expand(
        [
            (
                "generation",
                "$ai_generation",
                {"$ai_trace_id": "trace-1", "$ai_model": "gpt-4"},
                {
                    "$ai_input": [{"role": "user", "content": "how do i reset my password"}],
                    "$ai_output_choices": [{"role": "assistant", "content": "open account settings"}],
                },
                ["how do i reset my password", "open account settings"],
            ),
            (
                "span",
                "$ai_span",
                {"$ai_trace_id": "trace-1", "$ai_span_id": "span-1", "$ai_span_name": "fetch-docs"},
                {"$ai_input_state": {"query": "docs"}, "$ai_output_state": {"documents": 3}},
                ["fetch-docs", "query", "documents"],
            ),
        ]
    )
    @patch("products.ai_observability.backend.api.summarization.summarize")
    def test_summarizes_content_that_lives_only_in_ai_events(
        self, _name, event, metadata, content, expected, mock_summarize
    ):
        self._approve_ai_processing()
        mock_summarize.return_value = SummarizationResponse(
            title="Event Summary",
            flow_diagram="Start\n    |\nComplete",
            summary_bullets=[SummaryBullet(text="Handled the request", line_refs="L1")],
            interesting_notes=[],
        )

        event_uuid = uuid.uuid4()
        timestamp = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        self._ingest_ai_event(event, event_uuid, timestamp, metadata, content)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            {
                "generation_id": str(event_uuid),
                "mode": "minimal",
                "date_from": (timestamp - timedelta(days=1)).isoformat(),
                "date_to": (timestamp + timedelta(days=1)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        text_repr = response.data["text_repr"].lower()
        for fragment in expected:
            self.assertIn(fragment, text_repr)

    @patch("products.ai_observability.backend.api.summarization.summarize")
    def test_summarizes_an_event_predating_the_ai_events_split(self, mock_summarize):
        """Events older than the ai_events retention window still hold their content inline."""
        self._approve_ai_processing()
        mock_summarize.return_value = SummarizationResponse(
            title="Event Summary",
            flow_diagram="Start\n    |\nComplete",
            summary_bullets=[SummaryBullet(text="Handled the request", line_refs="L1")],
            interesting_notes=[],
        )

        event_uuid = uuid.uuid4()
        timestamp = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        bulk_create_events(
            [
                {
                    "event": "$ai_generation",
                    "team": self.team,
                    "distinct_id": "user-1",
                    "timestamp": timestamp,
                    "event_uuid": str(event_uuid),
                    "properties": {
                        "$ai_trace_id": "trace-1",
                        "$ai_input": [{"role": "user", "content": "how do i reset my password"}],
                    },
                }
            ]
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            {
                "generation_id": str(event_uuid),
                "mode": "minimal",
                "date_from": (timestamp - timedelta(days=1)).isoformat(),
                "date_to": (timestamp + timedelta(days=1)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn("how do i reset my password", response.data["text_repr"].lower())

    def test_unknown_event_uuid_is_reported_as_not_found(self):
        self._approve_ai_processing()

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            {"generation_id": str(uuid.uuid4()), "mode": "minimal", "date_from": "-7d"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("not found", response.data["detail"])

    @patch("products.ai_observability.backend.api.summarization.summarize")
    def test_returns_cached_trace_when_source_trace_is_unavailable(self, mock_summarize):
        self._approve_ai_processing()
        mock_summarize.return_value = SummarizationResponse(
            title="Cached Trace Summary",
            flow_diagram="Start\n    |\nComplete",
            summary_bullets=[SummaryBullet(text="Trace completed", line_refs="L1")],
            interesting_notes=[],
        )
        trace_id = f"cached-trace-{uuid.uuid4()}"

        initial_response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            {
                "summarize_type": "trace",
                "mode": "minimal",
                "data": {
                    "trace": {"id": trace_id, "properties": {"$ai_span_name": "cached-trace"}},
                    "hierarchy": [],
                },
            },
            format="json",
        )
        cached_response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            {"trace_id": trace_id, "mode": "minimal", "date_from": "-7d"},
            format="json",
        )

        self.assertEqual(initial_response.status_code, status.HTTP_200_OK, initial_response.data)
        self.assertEqual(cached_response.status_code, status.HTTP_200_OK, cached_response.data)
        self.assertEqual(cached_response.data["summary"]["title"], "Cached Trace Summary")
        self.assertEqual(mock_summarize.call_count, 1)
