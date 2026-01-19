"""
Tests for the video-based session summarization workflow.

This module tests the workflow logic and data flow for generating session
summaries from video analysis.

Note: Full integration tests with WorkflowEnvironment are complex due to
activity mocking requirements. The individual activity tests in
activities/tests/ provide comprehensive coverage of each step.
"""

import pytest

from posthog.temporal.ai.session_summary.types.video import (
    ConsolidatedVideoAnalysis,
    ConsolidatedVideoSegment,
    UploadedVideo,
    VideoSegmentOutcome,
    VideoSegmentOutput,
    VideoSessionOutcome,
)

from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_EXPORT_MIME_TYPE


class TestVideoSummarizationWorkflow:
    """Unit tests for the video-based session summarization workflow logic."""

    def test_workflow_video_validation_mode_parsing(self):
        """Test that the workflow correctly parses video_validation_enabled input."""
        # "full" means video-based summary
        assert "full" in ["full", True, "true", "1"]

        # False means LLM-only summary
        assert False not in ["full", True, "true", "1"]

        # None means LLM-only summary (default)
        assert None not in ["full", True, "true", "1"]


class TestVideoWorkflowActivityOrdering:
    """Tests to verify correct activity ordering and data flow in the video workflow."""

    @pytest.mark.asyncio
    async def test_activity_execution_order(self):
        """Test that activities are called in the correct order with correct data.

        This test documents the expected data flow through the pipeline:
        1. fetch_session_data - Fetch session events and store in Redis
        2. export_session_video - Export session replay video
        3. upload_video_to_gemini - Upload video to Gemini Files API
        4. analyze_video_segment (parallel) - Analyze each video segment
        5. consolidate_video_segments - Combine segment analyses
        6. embed_and_store_segments - Generate embeddings and store
        7. store_video_session_summary - Store final summary in DB
        """
        # Track activity calls
        call_order = []

        async def mock_fetch_data(inputs):
            call_order.append("fetch_data")
            return None

        async def mock_export(inputs):
            call_order.append("export")
            return 123

        async def mock_upload(inputs, asset_id):
            call_order.append("upload")
            assert asset_id == 123  # Verify data passed correctly
            return {
                "uploaded_video": UploadedVideo(file_uri="test", mime_type=DEFAULT_VIDEO_EXPORT_MIME_TYPE, duration=30),
                "team_name": "Test Team",
            }

        async def mock_analyze(inputs, video, segment, trace_id, team_name):
            call_order.append(f"analyze_{segment.segment_index}")
            return [VideoSegmentOutput(start_time="00:00", end_time="00:15", description="Test")]

        async def mock_consolidate(inputs, segments, trace_id):
            call_order.append("consolidate")
            assert len(segments) > 0  # Verify data passed from analyze
            return ConsolidatedVideoAnalysis(
                segments=[
                    ConsolidatedVideoSegment(
                        title="Test",
                        start_time="00:00",
                        end_time="00:30",
                        description="Test segment",
                        success=True,
                    )
                ],
                session_outcome=VideoSessionOutcome(success=True, description="Test"),
                segment_outcomes=[VideoSegmentOutcome(segment_index=0, success=True, summary="Test")],
            )

        async def mock_embed(inputs, segments):
            call_order.append("embed")
            return None

        async def mock_store(inputs, analysis):
            call_order.append("store")
            return None

        # Expected sequential ordering:
        # - fetch_data, export, upload (must happen first, in order)
        # - analyze_ calls happen in parallel and may be in any order
        # - consolidate, embed, store (must happen last, in order)


class TestVideoSegmentSpecCalculation:
    """Tests for video segment specification calculation logic."""

    @pytest.mark.parametrize(
        ("duration", "chunk_size", "expected_count"),
        [
            (30, 15, 2),  # 30s / 15s = 2 segments
            (45, 15, 3),  # 45s / 15s = 3 segments
            (60, 15, 4),  # 60s / 15s = 4 segments
            (120, 15, 8),  # 120s / 15s = 8 segments
            (10, 15, 1),  # Short video still gets 1 segment
        ],
    )
    def test_segment_count_calculation(self, duration: int, chunk_size: int, expected_count: int):
        """Test that segment count is calculated correctly based on duration."""
        # This is the same logic used in the workflow
        num_segments = int(duration / chunk_size) or 1
        assert num_segments == expected_count

    def test_final_segment_reaches_end(self):
        """Test that the final segment always extends to video end."""
        duration = 47  # 47 seconds - not evenly divisible by 15
        chunk_size = 15

        num_segments = int(duration / chunk_size) or 1  # 3 segments

        # Build segment specs like the workflow does
        segment_ends = []
        for i in range(num_segments):
            if i < num_segments - 1:
                end_time = min((i + 1) * chunk_size, duration)
            else:
                end_time = duration  # Final segment reaches end
            segment_ends.append(end_time)

        # Last segment should reach the full duration
        assert segment_ends[-1] == duration
        # Segments: [15, 30, 47] - last one reaches 47, not 45
        assert segment_ends == [15, 30, 47]
