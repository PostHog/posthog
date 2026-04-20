"""Tests for the VideoSegmentClusteringWorkflow.

The test data is stored in two files in this directory:
- `mock_video_segments.yaml.gz` - Gzip-compressed YAML containing segment metadata
  (document_id, session_id, timestamps, content/descriptions, etc.)
  Compressed to reduce repo size. Decompress with `gunzip -k` to inspect.
- `mock_video_segments_embeddings.npy` - The 3072-dimensional embeddings as a NumPy binary array.
  Stored separately because embeddings are large binary blobs (float32 arrays) that would bloat the YAML file and
  make it unreadable. The array is indexed to match the order of segments in the YAML file.
"""

import gzip
import uuid
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
import numpy as np
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.ai.video_segment_clustering.activities import cluster_segments_activity
from posthog.temporal.ai.video_segment_clustering.clustering_workflow import VideoSegmentClusteringWorkflow
from posthog.temporal.ai.video_segment_clustering.models import (
    ClusteringWorkflowInputs,
    EmitSignalsActivityInputs,
    EmitSignalsResult,
    FetchSegmentsActivityInputs,
    FetchSegmentsResult,
    VideoSegment,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.asyncio,
]


# Store test data globally so mocked activities can access it
_test_segments: list[VideoSegment] = []

MOCK_STORAGE_KEY = "video_segment_clustering/test-mock/segments.json.gz"


@activity.defn(name="fetch_segments_activity")
async def mock_fetch_segments_activity(_inputs: FetchSegmentsActivityInputs) -> FetchSegmentsResult:
    """Return pre-loaded test segments via storage_key (S3 bypass)."""
    return FetchSegmentsResult(storage_key=MOCK_STORAGE_KEY, document_count=len(_test_segments))


@activity.defn(name="emit_signals_from_clusters_activity")
async def mock_emit_signals_activity(inputs: EmitSignalsActivityInputs) -> EmitSignalsResult:
    """Mock emit activity that tracks calls without LLM or emit_signal()."""
    return EmitSignalsResult(signals_emitted=len(inputs.clusters), clusters_skipped=0)


def load_test_data() -> tuple[list[dict], np.ndarray]:
    """Load test segments and embeddings from files."""
    yaml_path = Path(__file__).parent / "mock_video_segments.yaml.gz"
    npy_path = Path(__file__).parent / "mock_video_segments_embeddings.npy"

    with gzip.open(yaml_path, "rt") as f:
        data = yaml.safe_load(f)

    embeddings = np.load(npy_path)
    segments = data["segments"]

    return segments, embeddings


@pytest.fixture
def test_segments_and_embeddings():
    """Load test segments with their embeddings and populate global state for mocked activities."""
    global _test_segments

    segments, embeddings = load_test_data()

    _test_segments = []
    for i, segment in enumerate(segments):
        metadata = segment.get("metadata", {})
        _test_segments.append(
            VideoSegment(
                document_id=segment["document_id"],
                session_id=metadata.get("session_id", ""),
                start_time=metadata.get("start_time", ""),
                end_time=metadata.get("end_time", ""),
                session_start_time=metadata.get("session_start_time", ""),
                session_end_time=metadata.get("session_end_time", ""),
                session_duration=metadata.get("session_duration", 0),
                session_active_seconds=metadata.get("session_active_seconds", 0),
                distinct_id=metadata.get("distinct_id", ""),
                content=segment["content"],
                embedding=embeddings[i].tolist(),
            )
        )

    return {"segments": _test_segments, "embeddings": embeddings, "segment_count": len(segments)}


async def _mock_load_fetch_result(key: str) -> tuple[list[VideoSegment], list[str]]:
    """Return test segments and distinct_ids for mock storage key."""
    if key != MOCK_STORAGE_KEY:
        raise ValueError(f"Unknown storage key: {key}")
    distinct_ids = list({s.distinct_id for s in _test_segments if s.distinct_id})
    return _test_segments, distinct_ids


async def test_video_segment_clustering_workflow_emits_signals(ateam, test_segments_and_embeddings):
    """Test that the workflow clusters segments and emits signals."""
    team_id = ateam.id

    async with await WorkflowEnvironment.start_time_skipping() as env:
        task_queue = f"test-video-clustering-{uuid.uuid4()}"

        with (
            patch(
                "posthog.temporal.ai.video_segment_clustering.activities.a3_cluster_segments.load_fetch_result",
                side_effect=_mock_load_fetch_result,
            ),
            patch(
                "posthog.temporal.ai.video_segment_clustering.activities.a4_emit_signals_from_clusters.load_fetch_result",
                side_effect=_mock_load_fetch_result,
            ),
        ):
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[VideoSegmentClusteringWorkflow],
                activities=[
                    mock_fetch_segments_activity,
                    cluster_segments_activity,
                    mock_emit_signals_activity,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                workflow_inputs = ClusteringWorkflowInputs(
                    team_id=team_id,
                    lookback_hours=24,
                    min_segments=3,
                    skip_priming=True,
                )

                result = await env.client.execute_workflow(
                    VideoSegmentClusteringWorkflow.run,
                    workflow_inputs,
                    id=f"test-video-clustering-{uuid.uuid4()}",
                    task_queue=task_queue,
                )

                assert result is not None
                assert result.signals_emitted > 0


async def test_emit_signals_activity_calls_emit_signal(ateam, test_segments_and_embeddings):
    """Test that the emit signals activity calls emit_signal() for each labeled cluster."""
    from posthog.temporal.ai.video_segment_clustering.models import Cluster

    mock_emit = AsyncMock()
    mock_genai_response = AsyncMock()
    mock_genai_response.text = '{"actionable": true, "title": "Test issue", "description": "Test description"}'
    mock_genai_client = AsyncMock()
    mock_genai_client.models.generate_content.return_value = mock_genai_response

    segments = _test_segments[:6]
    clusters = [
        Cluster(cluster_id=0, segment_ids=[s.document_id for s in segments[:3]], size=3),
        Cluster(cluster_id=1, segment_ids=[s.document_id for s in segments[3:6]], size=3),
    ]

    inputs = EmitSignalsActivityInputs(
        team_id=ateam.id,
        clusters=clusters,
        storage_key=MOCK_STORAGE_KEY,
    )

    mock_activity_info = MagicMock()
    mock_activity_info.workflow_id = "test-workflow-id"

    with (
        patch(
            "posthog.temporal.ai.video_segment_clustering.activities.a4_emit_signals_from_clusters.load_fetch_result",
            side_effect=_mock_load_fetch_result,
        ),
        patch(
            "posthog.temporal.ai.video_segment_clustering.activities.a4_emit_signals_from_clusters.emit_signal",
            mock_emit,
        ),
        patch(
            "posthog.temporal.ai.video_segment_clustering.activities.a4_emit_signals_from_clusters.genai"
        ) as mock_genai_module,
        patch(
            "posthog.temporal.ai.video_segment_clustering.activities.a4_emit_signals_from_clusters.count_distinct_persons",
            return_value=3,
        ),
        patch(
            "posthog.temporal.ai.video_segment_clustering.priority.count_distinct_persons",
            return_value=3,
        ),
        patch(
            "posthog.temporal.ai.video_segment_clustering.activities.a4_emit_signals_from_clusters.activity.info",
            return_value=mock_activity_info,
        ),
    ):
        mock_genai_module.AsyncClient.return_value = mock_genai_client

        from posthog.temporal.ai.video_segment_clustering.activities.a4_emit_signals_from_clusters import (
            emit_signals_from_clusters_activity,
        )

        result = await emit_signals_from_clusters_activity(inputs)

    assert result.signals_emitted == 2
    assert result.clusters_skipped == 0
    assert mock_emit.call_count == 2

    # Verify emit_signal was called with correct source_product and source_type
    for call in mock_emit.call_args_list:
        assert call.kwargs["source_product"] == "session_replay"
        assert call.kwargs["source_type"] == "session_segment_cluster"
        assert call.kwargs["weight"] > 0
        assert "segments" in call.kwargs["extra"]
        assert "metrics" in call.kwargs["extra"]
