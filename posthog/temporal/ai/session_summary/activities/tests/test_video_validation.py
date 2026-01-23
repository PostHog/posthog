"""
Tests for video_validation: validate_llm_single_session_summary_with_videos_activity

This activity validates an existing LLM-generated session summary using video analysis.
"""

from collections.abc import Callable

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.exceptions import ApplicationError

from posthog.models import Team
from posthog.models.user import User
from posthog.temporal.ai.session_summary.activities.video_validation import (
    validate_llm_single_session_summary_with_videos_activity,
)
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs

from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_UNDERSTANDING_MODEL
from ee.models.session_summaries import SessionSummaryRunMeta, SingleSessionSummary

pytestmark = pytest.mark.django_db


@pytest.fixture
def mock_single_session_inputs_factory() -> Callable:
    """Factory to produce SingleSessionSummaryInputs for testing."""

    def _create_inputs(
        session_id: str,
        team_id: int,
        user_id: int,
        redis_key_base: str = "test_key_base",
        model_to_use: str = DEFAULT_VIDEO_UNDERSTANDING_MODEL,
    ) -> SingleSessionSummaryInputs:
        return SingleSessionSummaryInputs(
            session_id=session_id,
            user_id=user_id,
            team_id=team_id,
            redis_key_base=redis_key_base,
            model_to_use=model_to_use,
        )

    return _create_inputs


class TestValidateLlmSingleSessionSummaryWithVideosActivity:
    @pytest.mark.asyncio
    async def test_validate_summary_updates_existing(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_single_session_inputs_factory: Callable,
    ):
        """Test that validation updates existing summary with visual_confirmation."""
        inputs = mock_single_session_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        # Create existing summary without visual confirmation
        existing_summary = await SingleSessionSummary.objects.acreate(
            team_id=ateam.id,
            session_id=mock_video_session_id,
            summary={
                "segments": [
                    {
                        "index": 0,
                        "name": "Test segment",
                        "start_event_id": "e1000001",
                        "end_event_id": "e1000002",
                        "meta": {
                            "duration": 60,
                            "duration_percentage": 1.0,
                            "events_count": 10,
                            "events_percentage": 1.0,
                            "key_action_count": 1,
                            "failure_count": 0,
                        },
                    }
                ],
                "key_actions": [
                    {
                        "segment_index": 0,
                        "events": [
                            {
                                "event_id": "e1000001",
                                "event": "$pageview",
                                "description": "Test event",
                                "timestamp": "2025-01-01T00:00:00Z",
                                "milliseconds_since_start": 0,
                                "abandonment": False,
                                "confusion": False,
                                "exception": None,
                            }
                        ],
                    }
                ],
                "segment_outcomes": [{"segment_index": 0, "summary": "Test", "success": True}],
                "session_outcome": {"success": True, "description": "Test outcome"},
            },
            run_metadata={"model_used": "test", "visual_confirmation": False},
            created_by_id=auser.id,
        )

        # Mock the video validator to return updated summary
        mock_updated_summary = MagicMock()
        mock_updated_summary.data = existing_summary.summary
        # Use real dataclass instead of MagicMock because the code calls asdict() on it
        mock_updated_run_metadata = SessionSummaryRunMeta(
            model_used="test",
            visual_confirmation=True,
            visual_confirmation_results=None,
        )

        mock_validator = MagicMock()
        mock_validator.validate_session_summary_with_videos = AsyncMock(
            return_value=(mock_updated_summary, mock_updated_run_metadata)
        )

        try:
            with (
                patch("temporalio.activity.info") as mock_activity_info,
                patch(
                    "posthog.temporal.ai.session_summary.activities.video_validation.SessionSummaryVideoValidator",
                    return_value=mock_validator,
                ),
            ):
                mock_activity_info.return_value.workflow_id = "test_workflow_id"

                await validate_llm_single_session_summary_with_videos_activity(inputs)

                # Verify summary was updated
                updated_summary = await SingleSessionSummary.objects.aget(id=existing_summary.id)
                assert updated_summary.run_metadata is not None
                assert updated_summary.run_metadata["visual_confirmation"] is True
        finally:
            await existing_summary.adelete()

    @pytest.mark.asyncio
    async def test_validate_summary_skips_already_confirmed(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_single_session_inputs_factory: Callable,
    ):
        """Test that already visually confirmed summaries are skipped."""
        inputs = mock_single_session_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        # Create summary already marked as visually confirmed
        existing_summary = await SingleSessionSummary.objects.acreate(
            team_id=ateam.id,
            session_id=mock_video_session_id,
            summary={
                "segments": [],
                "key_actions": [],
                "segment_outcomes": [],
                "session_outcome": {"success": True, "description": "Test"},
            },
            run_metadata={"model_used": "test", "visual_confirmation": True},
            created_by_id=auser.id,
        )

        try:
            with patch(
                "posthog.temporal.ai.session_summary.activities.video_validation.SessionSummaryVideoValidator"
            ) as mock_validator_class:
                await validate_llm_single_session_summary_with_videos_activity(inputs)

                # Should not call validator (function returns None implicitly)
                mock_validator_class.assert_not_called()
        finally:
            await existing_summary.adelete()

    @pytest.mark.asyncio
    async def test_validate_summary_not_found_raises_error(
        self,
        ateam: Team,
        auser: User,
        mock_single_session_inputs_factory: Callable,
    ):
        """Test that missing summary raises ApplicationError."""
        non_existent_session_id = "00000000-0000-0000-9999-000000000000"
        inputs = mock_single_session_inputs_factory(non_existent_session_id, ateam.id, auser.id)

        with pytest.raises(ApplicationError, match="Summary not found"):
            await validate_llm_single_session_summary_with_videos_activity(inputs)

    @pytest.mark.asyncio
    async def test_validate_summary_user_not_found_raises_error(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_single_session_inputs_factory: Callable,
    ):
        """Test that missing user raises ApplicationError."""
        non_existent_user_id = 99999999
        inputs = mock_single_session_inputs_factory(mock_video_session_id, ateam.id, non_existent_user_id)

        # Create summary that exists - validation happens after user check, so we need minimal valid summary
        existing_summary = await SingleSessionSummary.objects.acreate(
            team_id=ateam.id,
            session_id=mock_video_session_id,
            summary={
                "segments": [
                    {
                        "index": 0,
                        "name": "Test",
                        "start_event_id": "e1000001",
                        "end_event_id": "e1000002",
                        "meta": {},
                    }
                ],
                "key_actions": [
                    {
                        "segment_index": 0,
                        "events": [
                            {
                                "event_id": "e1000001",
                                "description": "Test",
                                "abandonment": False,
                                "confusion": False,
                                "exception": None,
                            }
                        ],
                    }
                ],
                "segment_outcomes": [{"segment_index": 0, "summary": "Test", "success": True}],
                "session_outcome": {"success": True, "description": "Test"},
            },
            run_metadata={"model_used": "test", "visual_confirmation": False},
            created_by_id=auser.id,
        )

        try:
            with pytest.raises(ApplicationError, match="User not found"):
                await validate_llm_single_session_summary_with_videos_activity(inputs)
        finally:
            await existing_summary.adelete()

    @pytest.mark.asyncio
    async def test_validate_summary_no_result_returns_none(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_single_session_inputs_factory: Callable,
    ):
        """Test that None video validation result returns None without updating."""
        inputs = mock_single_session_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        existing_summary = await SingleSessionSummary.objects.acreate(
            team_id=ateam.id,
            session_id=mock_video_session_id,
            summary={
                "segments": [
                    {
                        "index": 0,
                        "name": "Test segment",
                        "start_event_id": "e1000001",
                        "end_event_id": "e1000002",
                        "meta": {
                            "duration": 60,
                            "duration_percentage": 1.0,
                            "events_count": 10,
                            "events_percentage": 1.0,
                            "key_action_count": 1,
                            "failure_count": 0,
                        },
                    }
                ],
                "key_actions": [
                    {
                        "segment_index": 0,
                        "events": [
                            {
                                "event_id": "e1000001",
                                "event": "$pageview",
                                "description": "Test event",
                                "timestamp": "2025-01-01T00:00:00Z",
                                "milliseconds_since_start": 0,
                                "abandonment": False,
                                "confusion": False,
                                "exception": None,
                            }
                        ],
                    }
                ],
                "segment_outcomes": [{"segment_index": 0, "summary": "Test", "success": True}],
                "session_outcome": {"success": True, "description": "Test"},
            },
            run_metadata={"model_used": "test", "visual_confirmation": False},
            created_by_id=auser.id,
        )

        mock_validator = MagicMock()
        mock_validator.validate_session_summary_with_videos = AsyncMock(return_value=None)

        try:
            with (
                patch("temporalio.activity.info") as mock_activity_info,
                patch(
                    "posthog.temporal.ai.session_summary.activities.video_validation.SessionSummaryVideoValidator",
                    return_value=mock_validator,
                ),
            ):
                mock_activity_info.return_value.workflow_id = "test_workflow_id"

                await validate_llm_single_session_summary_with_videos_activity(inputs)

                # Summary should remain unchanged
                summary = await SingleSessionSummary.objects.aget(id=existing_summary.id)
                assert summary.run_metadata is not None
                assert summary.run_metadata["visual_confirmation"] is False
        finally:
            await existing_summary.adelete()

    @pytest.mark.asyncio
    async def test_validate_summary_with_focus_area_context(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
    ):
        """Test validation with extra_summary_context containing focus_area."""
        from ee.models.session_summaries import ExtraSummaryContext

        extra_context = ExtraSummaryContext(focus_area="checkout_flow")
        inputs = SingleSessionSummaryInputs(
            session_id=mock_video_session_id,
            user_id=auser.id,
            team_id=ateam.id,
            redis_key_base="test_key_base",
            model_to_use=DEFAULT_VIDEO_UNDERSTANDING_MODEL,
            extra_summary_context=extra_context,
        )

        # Create summary with matching extra context (stored as dict)
        from dataclasses import asdict

        existing_summary = await SingleSessionSummary.objects.acreate(
            team_id=ateam.id,
            session_id=mock_video_session_id,
            extra_summary_context=asdict(extra_context),
            summary={
                "segments": [
                    {
                        "index": 0,
                        "name": "Checkout flow",
                        "start_event_id": "e1",
                        "end_event_id": "e2",
                        "meta": {
                            "duration": 60,
                            "duration_percentage": 1.0,
                            "events_count": 10,
                            "events_percentage": 1.0,
                            "key_action_count": 1,
                            "failure_count": 0,
                        },
                    }
                ],
                "key_actions": [
                    {
                        "segment_index": 0,
                        "events": [
                            {
                                "event_id": "e1",
                                "event": "$pageview",
                                "description": "Test event",
                                "timestamp": "2025-01-01T00:00:00Z",
                                "milliseconds_since_start": 0,
                            }
                        ],
                    }
                ],
                "segment_outcomes": [{"segment_index": 0, "summary": "Checkout completed", "success": True}],
                "session_outcome": {"success": True, "description": "User completed checkout"},
            },
            run_metadata={"model_used": "test", "visual_confirmation": True},
            created_by_id=auser.id,
        )

        try:
            # Should find the summary with matching context and skip (already confirmed)
            await validate_llm_single_session_summary_with_videos_activity(inputs)
        finally:
            await existing_summary.adelete()
