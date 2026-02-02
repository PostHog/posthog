"""Tests for the VideoSegmentClusteringWorkflow.

The test data is stored in two files in the parent directory:

- `mock_video_segments.yaml` - Contains segment metadata (document_id, session_id,
  timestamps, content/descriptions, etc.) in a human-readable format. This file can
  be inspected and manually edited if needed.

- `mock_video_segments_embeddings.npy` - Contains the 3072-dimensional embeddings
  as a NumPy binary array. Stored separately because embeddings are large binary
  blobs (float32 arrays) that would bloat the YAML file and make it unreadable.
  The array is indexed to match the order of segments in the YAML file.

This split format keeps metadata inspectable while efficiently storing the dense
embedding vectors that are essential for clustering but not human-readable.
"""

import uuid
from pathlib import Path

import pytest

import yaml
import numpy as np
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.ai.video_segment_clustering.activities import match_clusters_activity, persist_reports_activity
from posthog.temporal.ai.video_segment_clustering.models import (
    Cluster,
    ClusteringResult,
    ClusteringWorkflowInputs,
    ClusterLabel,
    ClusterSegmentsActivityInputs,
    FetchSegmentsActivityInputs,
    FetchSegmentsResult,
    LabelClustersActivityInputs,
    LabelingResult,
    PrimeSessionEmbeddingsActivityInputs,
    PrimeSessionEmbeddingsResult,
    VideoSegmentMetadata,
)
from posthog.temporal.ai.video_segment_clustering.workflow import VideoSegmentClusteringWorkflow

from products.signals.backend.models import SignalReport

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.asyncio,
]


# Store test data globally so mocked activities can access it
_test_segments: list[VideoSegmentMetadata] = []
_test_embeddings: np.ndarray = np.array([])


@activity.defn(name="prime_session_embeddings_activity")
async def mock_prime_activity(inputs: PrimeSessionEmbeddingsActivityInputs) -> PrimeSessionEmbeddingsResult:
    """Mock prime activity - skip priming as test data is already loaded."""
    return PrimeSessionEmbeddingsResult(session_ids_found=0, sessions_summarized=0, sessions_failed=0)


@activity.defn(name="fetch_segments_activity")
async def mock_fetch_segments_activity(inputs: FetchSegmentsActivityInputs) -> FetchSegmentsResult:
    """Mock fetch activity - return pre-loaded test segments."""
    return FetchSegmentsResult(segments=_test_segments)


@activity.defn(name="cluster_segments_activity")
async def mock_cluster_segments_activity(inputs: ClusterSegmentsActivityInputs) -> ClusteringResult:
    """Mock cluster activity - perform real clustering on pre-loaded embeddings."""
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics.pairwise import cosine_distances

    embeddings = _test_embeddings
    document_ids = inputs.document_ids

    if len(document_ids) == 0:
        return ClusteringResult(
            clusters=[],
            noise_segment_ids=[],
            labels=[],
            segment_to_cluster={},
        )

    doc_id_to_idx = {doc_id: idx for idx, doc_id in enumerate(document_ids)}
    indices = [doc_id_to_idx.get(doc_id) for doc_id in document_ids if doc_id in doc_id_to_idx]
    if not indices:
        return ClusteringResult(
            clusters=[],
            noise_segment_ids=[],
            labels=[],
            segment_to_cluster={},
        )

    cluster_embeddings = embeddings[: len(indices)]

    distance_matrix = cosine_distances(cluster_embeddings)
    clustering = AgglomerativeClustering(
        metric="precomputed",
        linkage="complete",
        distance_threshold=0.5,
        n_clusters=None,
    )
    labels = clustering.fit_predict(distance_matrix)

    clusters: list[Cluster] = []
    segment_to_cluster: dict[str, int] = {}

    unique_labels = set(labels)
    for label in unique_labels:
        cluster_indices = np.where(labels == label)[0]
        cluster_doc_ids = [document_ids[i] for i in cluster_indices]
        cluster_embs = cluster_embeddings[cluster_indices]
        centroid = np.mean(cluster_embs, axis=0)

        clusters.append(
            Cluster(
                cluster_id=int(label),
                segment_ids=cluster_doc_ids,
                centroid=centroid.tolist(),
                size=len(cluster_doc_ids),
            )
        )

        for doc_id in cluster_doc_ids:
            segment_to_cluster[doc_id] = int(label)

    labels_list = [int(labels[i]) for i in range(len(document_ids))]

    return ClusteringResult(
        clusters=clusters,
        noise_segment_ids=[],
        labels=labels_list,
        segment_to_cluster=segment_to_cluster,
    )


@activity.defn(name="label_clusters_activity")
async def mock_label_activity(inputs: LabelClustersActivityInputs) -> LabelingResult:
    """Mock label activity - return actionable labels without LLM."""
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
    yaml_path = Path(__file__).parent / "mock_video_segments.yaml"
    npy_path = Path(__file__).parent / "mock_video_segments_embeddings.npy"

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    embeddings = np.load(npy_path)
    segments = data["segments"]

    return segments, embeddings


@pytest.fixture
def test_segments_and_embeddings():
    """Load test segments with their embeddings and populate global state for mocked activities."""
    global _test_segments, _test_embeddings

    segments, embeddings = load_test_data()

    # Use a small subset of 50 segments to avoid gRPC message size limits
    # (clusters with 3072-dim centroids can exceed 4MB gRPC limit)
    max_segments = 50
    segments = segments[:max_segments]
    embeddings = embeddings[:max_segments]

    # Convert to VideoSegmentMetadata objects for the workflow
    _test_segments = []
    for segment in segments:
        metadata = segment.get("metadata", {})
        _test_segments.append(
            VideoSegmentMetadata(
                document_id=segment.get("document_id"),
                session_id=metadata.get("session_id", ""),
                start_time=metadata.get("start_time", ""),
                end_time=metadata.get("end_time", ""),
                session_start_time=metadata.get("session_start_time", ""),
                session_end_time=metadata.get("session_end_time", ""),
                session_duration=metadata.get("session_duration", 0),
                session_active_seconds=metadata.get("session_active_seconds", 0),
                distinct_id=metadata.get("distinct_id", ""),
                content=segment.get("content", ""),
            )
        )

    _test_embeddings = embeddings

    return {"segments": _test_segments, "embeddings": embeddings, "segment_count": len(segments)}


async def test_video_segment_clustering_workflow_creates_reports(ateam, test_segments_and_embeddings):
    """Test that the workflow runs and creates SignalReports from clustered video segments."""
    team_id = ateam.id

    async with await WorkflowEnvironment.start_time_skipping() as env:
        task_queue = f"test-video-clustering-{uuid.uuid4()}"

        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[VideoSegmentClusteringWorkflow],
            activities=[
                mock_prime_activity,
                mock_fetch_segments_activity,
                mock_cluster_segments_activity,
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

            reports = await sync_to_async(list)(
                SignalReport.objects.filter(team_id=team_id, status=SignalReport.Status.READY)
            )
            assert len(reports) > 0

            for report in reports:
                assert report.title
                assert report.summary
                assert report.cluster_centroid is not None
                assert len(report.cluster_centroid) == 3072
