"""
Tests for Activity 4: consolidate_video_segments_activity

This activity consolidates raw video segments into meaningful semantic segments using LLM.
"""

import json
from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
from temporalio.exceptions import ApplicationError

from posthog.models import Team
from posthog.models.user import User
from posthog.temporal.ai.session_summary.activities.a4_consolidate_video_segments import (
    consolidate_video_segments_activity,
)
from posthog.temporal.ai.session_summary.types.video import ConsolidatedVideoAnalysis, VideoSegmentOutput

pytestmark = pytest.mark.django_db


class TestConsolidateVideoSegmentsActivity:
    @pytest.mark.asyncio
    async def test_consolidate_segments_success(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
        mock_video_segment_outputs: list[VideoSegmentOutput],
        mock_consolidated_video_analysis: ConsolidatedVideoAnalysis,
        mock_gemini_consolidation_response: MagicMock,
    ):
        """Test successful consolidation of raw video segments."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

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
        mock_video_summary_inputs_factory: Callable,
    ):
        """Test that empty segment list raises ApplicationError."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        with pytest.raises(ApplicationError, match="No segments extracted"):
            await consolidate_video_segments_activity(
                inputs=inputs,
                raw_segments=[],
                trace_id="test-trace-id",
            )

    @pytest.mark.asyncio
    async def test_consolidate_segments_detects_issues(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
        mock_video_segment_outputs: list[VideoSegmentOutput],
    ):
        """Test that consolidation correctly identifies exceptions, confusion, and abandonment."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        # Response indicating issues were detected
        issue_response = {
            "segments": [
                {
                    "title": "Failed API configuration",
                    "start_time": "00:00",
                    "end_time": "00:30",
                    "description": "User tried to configure API but encountered errors",
                    "success": False,
                    "exception": "blocking",
                    "confusion_detected": True,
                    "abandonment_detected": True,
                },
            ],
            "session_outcome": {
                "success": False,
                "description": "User failed to complete configuration due to errors",
            },
            "segment_outcomes": [
                {
                    "segment_index": 0,
                    "success": False,
                    "summary": "Configuration failed",
                },
            ],
        }

        mock_response = MagicMock()
        mock_response.text = f"```json\n{json.dumps(issue_response)}\n```"

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

            assert result.segments[0].exception == "blocking"
            assert result.segments[0].confusion_detected is True
            assert result.segments[0].abandonment_detected is True
            assert result.session_outcome.success is False

    @pytest.mark.asyncio
    async def test_consolidate_segments_json_parsing_from_markdown(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
        mock_video_segment_outputs: list[VideoSegmentOutput],
        mock_consolidated_video_analysis: ConsolidatedVideoAnalysis,
    ):
        """Test that JSON is correctly extracted from markdown code block."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        # Response wrapped in markdown code block
        mock_response = MagicMock()
        mock_response.text = f"```json\n{json.dumps(mock_consolidated_video_analysis.model_dump())}\n```"

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
    async def test_consolidate_segments_json_parsing_without_markdown(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
        mock_video_segment_outputs: list[VideoSegmentOutput],
        mock_consolidated_video_analysis: ConsolidatedVideoAnalysis,
    ):
        """Test that raw JSON (without markdown block) is also parsed correctly."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        # Raw JSON response without markdown
        mock_response = MagicMock()
        mock_response.text = json.dumps(mock_consolidated_video_analysis.model_dump())

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
        mock_video_summary_inputs_factory: Callable,
        mock_video_segment_outputs: list[VideoSegmentOutput],
    ):
        """Test that invalid JSON in response raises error."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

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
        mock_video_summary_inputs_factory: Callable,
        mock_video_segment_outputs: list[VideoSegmentOutput],
    ):
        """Test that missing required fields in response raises validation error."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        # Response missing required fields
        incomplete_response: dict[str, Any] = {
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

    @pytest.mark.asyncio
    async def test_consolidate_segments_with_non_blocking_exception(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
        mock_video_segment_outputs: list[VideoSegmentOutput],
    ):
        """Test that non-blocking exceptions are correctly identified."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        response_data = {
            "segments": [
                {
                    "title": "Minor error during navigation",
                    "start_time": "00:00",
                    "end_time": "00:30",
                    "description": "User saw a warning toast but continued normally",
                    "success": True,
                    "exception": "non-blocking",
                    "confusion_detected": False,
                    "abandonment_detected": False,
                },
            ],
            "session_outcome": {
                "success": True,
                "description": "User completed their task despite minor warnings",
            },
            "segment_outcomes": [
                {
                    "segment_index": 0,
                    "success": True,
                    "summary": "Completed despite warning",
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

            assert result.segments[0].exception == "non-blocking"
            assert result.segments[0].success is True
            assert result.session_outcome.success is True
