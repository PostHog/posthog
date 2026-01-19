"""
Tests for Activity 5: embed_and_store_segments_activity

This activity generates embeddings for video segments and produces to Kafka for ClickHouse storage.
"""

from collections.abc import Callable

import pytest
from unittest.mock import patch

from posthog.models import Team
from posthog.models.user import User
from posthog.temporal.ai.session_summary.activities.a5_embed_and_store_segments import (
    SESSION_SEGMENTS_EMBEDDING_MODEL,
    embed_and_store_segments_activity,
)
from posthog.temporal.ai.session_summary.types.video import VideoSegmentOutput

pytestmark = pytest.mark.django_db


class TestEmbedAndStoreSegmentsActivity:
    @pytest.mark.asyncio
    async def test_embed_and_store_segments_emits_requests(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
        mock_video_segment_outputs: list[VideoSegmentOutput],
    ):
        """Test that embedding requests are emitted for each segment."""
        inputs = mock_video_summary_inputs_factory(
            mock_video_session_id, ateam.id, auser.id, user_distinct_id_to_log="test_distinct_id"
        )

        with patch(
            "posthog.temporal.ai.session_summary.activities.a5_embed_and_store_segments.emit_embedding_request"
        ) as mock_emit:
            await embed_and_store_segments_activity(
                inputs=inputs,
                segments=mock_video_segment_outputs,
            )

            # Should emit one request per segment
            assert mock_emit.call_count == len(mock_video_segment_outputs)

            # Verify first call arguments
            first_call = mock_emit.call_args_list[0]
            assert first_call.kwargs["team_id"] == ateam.id
            assert first_call.kwargs["product"] == "session-replay"
            assert first_call.kwargs["document_type"] == "video-segment"
            assert first_call.kwargs["rendering"] == "video-analysis"
            assert first_call.kwargs["models"] == [SESSION_SEGMENTS_EMBEDDING_MODEL.value]

    @pytest.mark.asyncio
    async def test_embed_and_store_segments_document_ids(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
        mock_video_segment_outputs: list[VideoSegmentOutput],
    ):
        """Test that document IDs are formatted correctly."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        with patch(
            "posthog.temporal.ai.session_summary.activities.a5_embed_and_store_segments.emit_embedding_request"
        ) as mock_emit:
            await embed_and_store_segments_activity(
                inputs=inputs,
                segments=mock_video_segment_outputs,
            )

            # Check document_id format for each call
            for i, call in enumerate(mock_emit.call_args_list):
                segment = mock_video_segment_outputs[i]
                expected_doc_id = f"{mock_video_session_id}:{segment.start_time}:{segment.end_time}"
                assert call.kwargs["document_id"] == expected_doc_id

    @pytest.mark.asyncio
    async def test_embed_and_store_segments_metadata(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
        mock_video_segment_outputs: list[VideoSegmentOutput],
    ):
        """Test that metadata is correctly included in embedding requests."""
        distinct_id = "test_user_distinct_id_123"
        inputs = mock_video_summary_inputs_factory(
            mock_video_session_id, ateam.id, auser.id, user_distinct_id_to_log=distinct_id
        )

        with patch(
            "posthog.temporal.ai.session_summary.activities.a5_embed_and_store_segments.emit_embedding_request"
        ) as mock_emit:
            await embed_and_store_segments_activity(
                inputs=inputs,
                segments=mock_video_segment_outputs,
            )

            first_segment = mock_video_segment_outputs[0]
            first_call = mock_emit.call_args_list[0]
            metadata = first_call.kwargs["metadata"]

            assert metadata["session_id"] == mock_video_session_id
            assert metadata["team_id"] == ateam.id
            assert metadata["distinct_id"] == distinct_id
            assert metadata["start_time"] == first_segment.start_time
            assert metadata["end_time"] == first_segment.end_time

    @pytest.mark.asyncio
    async def test_embed_and_store_segments_empty_list(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
    ):
        """Test that empty segment list doesn't emit any requests."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        with patch(
            "posthog.temporal.ai.session_summary.activities.a5_embed_and_store_segments.emit_embedding_request"
        ) as mock_emit:
            await embed_and_store_segments_activity(
                inputs=inputs,
                segments=[],
            )

            mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_embed_and_store_segments_uses_description_as_content(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
    ):
        """Test that segment description is used as embedding content."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        segments = [
            VideoSegmentOutput(
                start_time="00:00",
                end_time="00:15",
                description="User clicked on the dashboard button and navigated to analytics page",
            ),
        ]

        with patch(
            "posthog.temporal.ai.session_summary.activities.a5_embed_and_store_segments.emit_embedding_request"
        ) as mock_emit:
            await embed_and_store_segments_activity(
                inputs=inputs,
                segments=segments,
            )

            assert mock_emit.call_args.kwargs["content"] == segments[0].description

    @pytest.mark.asyncio
    async def test_embed_and_store_segments_propagates_error(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
        mock_video_segment_outputs: list[VideoSegmentOutput],
    ):
        """Test that errors from emit_embedding_request are propagated."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        with patch(
            "posthog.temporal.ai.session_summary.activities.a5_embed_and_store_segments.emit_embedding_request",
            side_effect=Exception("Kafka connection failed"),
        ):
            with pytest.raises(Exception, match="Kafka connection failed"):
                await embed_and_store_segments_activity(
                    inputs=inputs,
                    segments=mock_video_segment_outputs,
                )
