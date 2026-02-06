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
from unittest.mock import patch

import yaml
import numpy as np
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.ai.video_segment_clustering.activities import (
    cluster_segments_activity,
    match_clusters_activity,
    persist_reports_activity,
)
from posthog.temporal.ai.video_segment_clustering.clustering_workflow import VideoSegmentClusteringWorkflow
from posthog.temporal.ai.video_segment_clustering.models import (
    ClusteringWorkflowInputs,
    ClusterLabel,
    FetchSegmentsActivityInputs,
    FetchSegmentsResult,
    LabelClustersActivityInputs,
    LabelingResult,
    VideoSegment,
    VideoSegmentMetadata,
)

from products.signals.backend.models import SignalReport

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.asyncio,
]


# Store test data globally so mocked activities can access it
_test_segments: list[VideoSegmentMetadata] = []
_test_video_segments: list[VideoSegment] = []  # With embeddings, for clustering activity


@activity.defn(name="fetch_segments_activity")
async def mock_fetch_segments_activity(_inputs: FetchSegmentsActivityInputs) -> FetchSegmentsResult:
    """Return pre-loaded test segments."""
    return FetchSegmentsResult(segments=_test_segments)


@activity.defn(name="label_clusters_activity")
async def mock_label_activity(inputs: LabelClustersActivityInputs) -> LabelingResult:
    """Return actionable labels without LLM."""
    labels = {
        cluster.cluster_id: ClusterLabel(
            actionable=True,
            title=f"Investigate user friction pattern #{cluster.cluster_id}",
            description="Multiple users experiencing similar issues that should be investigated",
        )
        for cluster in inputs.clusters
    }
    return LabelingResult(labels=labels)


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
    global _test_segments, _test_video_segments

    segments, embeddings = load_test_data()

    # Convert to VideoSegmentMetadata objects for the workflow (without embeddings)
    _test_segments = []
    # Convert to VideoSegment objects for the clustering activity (with embeddings)
    _test_video_segments = []

    for i, segment in enumerate(segments):
        metadata = segment.get("metadata", {})
        common_fields = {
            "document_id": segment["document_id"],
            "session_id": metadata.get("session_id", ""),
            "start_time": metadata.get("start_time", ""),
            "end_time": metadata.get("end_time", ""),
            "session_start_time": metadata.get("session_start_time", ""),
            "session_end_time": metadata.get("session_end_time", ""),
            "session_duration": metadata.get("session_duration", 0),
            "session_active_seconds": metadata.get("session_active_seconds", 0),
            "distinct_id": metadata.get("distinct_id", ""),
            "content": segment["content"],
        }
        _test_segments.append(VideoSegmentMetadata(**common_fields))
        _test_video_segments.append(VideoSegment(**common_fields, embedding=embeddings[i].tolist()))

    return {"segments": _test_segments, "embeddings": embeddings, "segment_count": len(segments)}


async def _mock_fetch_embeddings_by_document_ids(_team, document_ids: list[str]) -> list[VideoSegment]:
    """Mock that returns pre-loaded VideoSegments with embeddings."""
    doc_id_to_segment = {s.document_id: s for s in _test_video_segments}
    return [doc_id_to_segment[doc_id] for doc_id in document_ids if doc_id in doc_id_to_segment]


async def test_video_segment_clustering_workflow_creates_reports(ateam, test_segments_and_embeddings):
    """Test that the workflow runs and creates SignalReports from clustered video segments."""
    team_id = ateam.id

    async with await WorkflowEnvironment.start_time_skipping() as env:
        task_queue = f"test-video-clustering-{uuid.uuid4()}"

        # Patch the data fetching layer to use pre-loaded test data
        with patch(
            "posthog.temporal.ai.video_segment_clustering.activities.a3_cluster_segments._fetch_embeddings_by_document_ids",
            side_effect=_mock_fetch_embeddings_by_document_ids,
        ):
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[VideoSegmentClusteringWorkflow],
                activities=[
                    mock_fetch_segments_activity,
                    cluster_segments_activity,  # Real activity with mocked data layer
                    match_clusters_activity,
                    mock_label_activity,
                    persist_reports_activity,
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

                assert result.success, f"Workflow failed: {result.error}"
                assert result.team_id == team_id
                assert result.segments_processed is not None, "Expected segments to be processed"
                assert result.segments_processed > 0
                assert result.clusters_found > 0
                assert result.reports_created > 0

                reports: list[SignalReport] = [
                    report
                    async for report in SignalReport.objects.filter(team_id=team_id, status=SignalReport.Status.READY)
                ]

                # Currently just asserting that the reports were created. If we were to test the actual contents,
                # that should rather be an AI eval, as clustering is not expected to be deterministic
                assert len(reports) > 0

                for report in reports:
                    assert report.title
                    assert report.summary
                    assert report.cluster_centroid is not None
                    assert len(report.cluster_centroid) == 3072
