"""
Tests for Activity 5: embed_and_store_segments_activity

This activity generates embeddings for video segments and produces to Kafka for ClickHouse storage.
"""

import pytest
from unittest.mock import patch

from posthog.models import Team
from posthog.models.user import User
from posthog.temporal.ai.session_summary.activities.a5_embed_and_store_segments import (
    SESSION_SEGMENTS_EMBEDDING_MODEL,
    embed_and_store_segments_activity,
)
from posthog.temporal.ai.session_summary.activities.tests.conftest import create_video_summary_inputs
from posthog.temporal.ai.session_summary.types.video import VideoSegmentOutput

pytestmark = pytest.mark.django_db


class TestEmbedAndStoreSegmentsActivity:
    @pytest.mark.asyncio
    async def test_embed_and_store_segments_emits_correct_requests(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_segment_outputs: list[VideoSegmentOutput],
    ):
        """
        Happy path: verifies embedding requests are emitted with correct document IDs, metadata, and content.

        This single test covers the complete embedding flow because all assertions verify
        the same emit_embedding_request call - document_id format, metadata fields, and content.
        """
        distinct_id = "test_user_distinct_id_123"
        inputs = create_video_summary_inputs(
            mock_video_session_id, ateam.id, auser.id, user_distinct_id_to_log=distinct_id
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

            # Verify each call has correct structure
            for i, call in enumerate(mock_emit.call_args_list):
                segment = mock_video_segment_outputs[i]

                # Document ID format: session_id:start_time:end_time
                expected_doc_id = f"{mock_video_session_id}:{segment.start_time}:{segment.end_time}"
                assert call.kwargs["document_id"] == expected_doc_id

                # Required parameters
                assert call.kwargs["team_id"] == ateam.id
                assert call.kwargs["product"] == "session-replay"
                assert call.kwargs["document_type"] == "video-segment"
                assert call.kwargs["rendering"] == "video-analysis"
                assert call.kwargs["models"] == [SESSION_SEGMENTS_EMBEDDING_MODEL.value]

                # Content is the segment description
                assert call.kwargs["content"] == segment.description

                # Metadata includes all required fields
                metadata = call.kwargs["metadata"]
                assert metadata["session_id"] == mock_video_session_id
                assert metadata["team_id"] == ateam.id
                assert metadata["distinct_id"] == distinct_id
                assert metadata["start_time"] == segment.start_time
                assert metadata["end_time"] == segment.end_time

    @pytest.mark.asyncio
    async def test_embed_and_store_segments_empty_list(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
    ):
        """
        No-op guard: empty segment list doesn't emit any requests.

        Nothing to embed means nothing to store - the function should be safe to call with empty input.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        with patch(
            "posthog.temporal.ai.session_summary.activities.a5_embed_and_store_segments.emit_embedding_request"
        ) as mock_emit:
            await embed_and_store_segments_activity(
                inputs=inputs,
                segments=[],
            )

            mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_embed_and_store_segments_propagates_error(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_segment_outputs: list[VideoSegmentOutput],
    ):
        """
        Error propagation: errors from emit_embedding_request bubble up.

        Kafka failures should not be silently swallowed - the caller needs to know.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        with patch(
            "posthog.temporal.ai.session_summary.activities.a5_embed_and_store_segments.emit_embedding_request",
            side_effect=Exception("Kafka connection failed"),
        ):
            with pytest.raises(Exception, match="Kafka connection failed"):
                await embed_and_store_segments_activity(
                    inputs=inputs,
                    segments=mock_video_segment_outputs,
                )
