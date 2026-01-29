"""
Tests for Activity 4: consolidate_video_segments_activity

This activity consolidates raw video segments into meaningful semantic segments using LLM.
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
from temporalio.exceptions import ApplicationError

from posthog.models import Team
from posthog.models.user import User
from posthog.temporal.ai.session_summary.activities.a4_consolidate_video_segments import (
    consolidate_video_segments_activity,
)
from posthog.temporal.ai.session_summary.activities.tests.conftest import create_video_summary_inputs
from posthog.temporal.ai.session_summary.types.video import ConsolidatedVideoAnalysis, VideoSegmentOutput

pytestmark = pytest.mark.django_db


class TestConsolidateVideoSegmentsActivity:
    @pytest.mark.asyncio
    async def test_consolidate_segments_success(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_segment_outputs: list[VideoSegmentOutput],
        mock_consolidated_video_analysis: ConsolidatedVideoAnalysis,
        mock_gemini_consolidation_response: MagicMock,
    ):
        """
        Happy path: raw video segments are consolidated into semantic segments.

        Verifies complete flow: LLM call, response parsing, and structured output.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        mock_client = MagicMock()
        mock_client.models.generate_content = AsyncMock(return_value=mock_gemini_consolidation_response)

        with patch(
            "posthog.temporal.ai.session_summary.activities.a4_consolidate_video_segments.genai.AsyncClient",
            return_value=mock_client,
        ):
            result = await consolidate_video_segments_activity(
                inputs=inputs,
                raw_segments=mock_video_segment_outputs,
                trace_id="test-trace-id",
            )

            assert isinstance(result, ConsolidatedVideoAnalysis)
            assert len(result.segments) == 2
            assert result.session_outcome.success is True
            assert len(result.segment_outcomes) == 2

            mock_client.models.generate_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_consolidate_segments_empty_input_raises_error(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
    ):
        """
        Guard clause: empty segment list raises ApplicationError.

        Cannot consolidate nothing - this indicates an upstream failure.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        with pytest.raises(ApplicationError, match="No segments extracted"):
            await consolidate_video_segments_activity(
                inputs=inputs,
                raw_segments=[],
                trace_id="test-trace-id",
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("exception_type", "success", "confusion", "abandonment"),
        [
            ("blocking", False, True, True),
            ("non-blocking", True, False, False),
        ],
        ids=["blocking_exception", "non_blocking_exception"],
    )
    async def test_consolidate_segments_classifies_exceptions(
        self,
        exception_type: str,
        success: bool,
        confusion: bool,
        abandonment: bool,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_segment_outputs: list[VideoSegmentOutput],
    ):
        """
        Exception classification: blocking vs non-blocking exceptions have different impacts.

        Blocking exceptions indicate failures, while non-blocking are minor issues the user worked around.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        response_data = {
            "segments": [
                {
                    "title": "Test segment",
                    "start_time": "00:00",
                    "end_time": "00:30",
                    "description": "Test description",
                    "success": success,
                    "exception": exception_type,
                    "confusion_detected": confusion,
                    "abandonment_detected": abandonment,
                },
            ],
            "session_outcome": {
                "success": success,
                "description": "Test outcome",
            },
            "segment_outcomes": [
                {
                    "segment_index": 0,
                    "success": success,
                    "summary": "Test summary",
                },
            ],
        }

        mock_response = MagicMock()
        mock_response.text = json.dumps(response_data)

        mock_client = MagicMock()
        mock_client.models.generate_content = AsyncMock(return_value=mock_response)

        with patch(
            "posthog.temporal.ai.session_summary.activities.a4_consolidate_video_segments.genai.AsyncClient",
            return_value=mock_client,
        ):
            result = await consolidate_video_segments_activity(
                inputs=inputs,
                raw_segments=mock_video_segment_outputs,
                trace_id="test-trace-id",
            )

            assert result.segments[0].exception == exception_type
            assert result.segments[0].success is success
            assert result.segments[0].confusion_detected is confusion
            assert result.segments[0].abandonment_detected is abandonment
            assert result.session_outcome.success is success

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("wrap_in_markdown",),
        [
            (True,),
            (False,),
        ],
        ids=["with_markdown", "without_markdown"],
    )
    async def test_consolidate_segments_parses_json_formats(
        self,
        wrap_in_markdown: bool,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_segment_outputs: list[VideoSegmentOutput],
        mock_consolidated_video_analysis: ConsolidatedVideoAnalysis,
    ):
        """
        JSON extraction: handles both markdown-wrapped and raw JSON responses.

        LLMs sometimes wrap JSON in markdown code blocks, sometimes they don't.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        json_content = json.dumps(mock_consolidated_video_analysis.model_dump())
        if wrap_in_markdown:
            response_text = f"```json\n{json_content}\n```"
        else:
            response_text = json_content

        mock_response = MagicMock()
        mock_response.text = response_text

        mock_client = MagicMock()
        mock_client.models.generate_content = AsyncMock(return_value=mock_response)

        with patch(
            "posthog.temporal.ai.session_summary.activities.a4_consolidate_video_segments.genai.AsyncClient",
            return_value=mock_client,
        ):
            result = await consolidate_video_segments_activity(
                inputs=inputs,
                raw_segments=mock_video_segment_outputs,
                trace_id="test-trace-id",
            )

            assert isinstance(result, ConsolidatedVideoAnalysis)

    @pytest.mark.asyncio
    async def test_consolidate_segments_invalid_json_raises_error(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_segment_outputs: list[VideoSegmentOutput],
    ):
        """
        Parse error: invalid JSON in response raises JSONDecodeError.

        We need valid JSON to construct the response - garbage in, error out.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        mock_response = MagicMock()
        mock_response.text = "This is not valid JSON at all"

        mock_client = MagicMock()
        mock_client.models.generate_content = AsyncMock(return_value=mock_response)

        with patch(
            "posthog.temporal.ai.session_summary.activities.a4_consolidate_video_segments.genai.AsyncClient",
            return_value=mock_client,
        ):
            with pytest.raises(json.JSONDecodeError):
                await consolidate_video_segments_activity(
                    inputs=inputs,
                    raw_segments=mock_video_segment_outputs,
                    trace_id="test-trace-id",
                )

    @pytest.mark.asyncio
    async def test_consolidate_segments_missing_fields_raises_validation_error(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_segment_outputs: list[VideoSegmentOutput],
    ):
        """
        Schema validation: missing required fields in response raises ValidationError.

        The response must conform to ConsolidatedVideoAnalysis schema.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        # Response missing required fields
        incomplete_response = {
            "segments": [],
            # Missing session_outcome and segment_outcomes
        }

        mock_response = MagicMock()
        mock_response.text = json.dumps(incomplete_response)

        mock_client = MagicMock()
        mock_client.models.generate_content = AsyncMock(return_value=mock_response)

        with patch(
            "posthog.temporal.ai.session_summary.activities.a4_consolidate_video_segments.genai.AsyncClient",
            return_value=mock_client,
        ):
            with pytest.raises(ValidationError):
                await consolidate_video_segments_activity(
                    inputs=inputs,
                    raw_segments=mock_video_segment_outputs,
                    trace_id="test-trace-id",
                )
