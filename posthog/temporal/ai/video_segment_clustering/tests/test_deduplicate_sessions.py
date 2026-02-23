from parameterized import parameterized

from posthog.temporal.ai.video_segment_clustering.activities.a3_cluster_segments import (
    _deduplicate_sessions_within_clusters,
)
from posthog.temporal.ai.video_segment_clustering.models import Cluster, ClusteringResult, VideoSegment


def _make_segment(document_id: str, session_id: str, embedding: list[float]) -> VideoSegment:
    return VideoSegment(
        document_id=document_id,
        session_id=session_id,
        start_time="0:00",
        end_time="0:30",
        session_start_time="2025-01-01T00:00:00Z",
        session_end_time="2025-01-01T01:00:00Z",
        session_duration=3600,
        session_active_seconds=1800,
        distinct_id=f"user-{session_id}",
        content="test content",
        embedding=embedding,
    )


class TestDeduplicateSessionsWithinClusters:
    @parameterized.expand(
        [
            (
                "no_duplicates_leaves_cluster_unchanged",
                # Two segments from different sessions — nothing to dedup
                [
                    _make_segment("s1:0:30", "s1", [1.0, 0.0, 0.0]),
                    _make_segment("s2:0:30", "s2", [0.9, 0.1, 0.0]),
                ],
                [Cluster(cluster_id=0, segment_ids=["s1:0:30", "s2:0:30"], size=2)],
                {0: [1.0, 0.0, 0.0]},
                # Expected: both segments kept
                ["s1:0:30", "s2:0:30"],
                [],
            ),
            (
                "duplicate_session_keeps_closest_to_centroid",
                # Two segments from same session — seg_a is closer to centroid [1,0,0]
                [
                    _make_segment("s1:0:30", "s1", [0.95, 0.05, 0.0]),
                    _make_segment("s1:30:60", "s1", [0.5, 0.5, 0.0]),
                ],
                [Cluster(cluster_id=0, segment_ids=["s1:0:30", "s1:30:60"], size=2)],
                {0: [1.0, 0.0, 0.0]},
                # Expected: s1:0:30 kept (closer), s1:30:60 dropped
                ["s1:0:30"],
                ["s1:30:60"],
            ),
            (
                "multiple_sessions_deduped_independently",
                # Session s1 has 2 segments, session s2 has 2 segments
                [
                    _make_segment("s1:0:30", "s1", [0.9, 0.1, 0.0]),
                    _make_segment("s1:30:60", "s1", [0.3, 0.7, 0.0]),
                    _make_segment("s2:0:30", "s2", [0.8, 0.2, 0.0]),
                    _make_segment("s2:30:60", "s2", [0.1, 0.9, 0.0]),
                ],
                [Cluster(cluster_id=0, segment_ids=["s1:0:30", "s1:30:60", "s2:0:30", "s2:30:60"], size=4)],
                {0: [1.0, 0.0, 0.0]},
                # Expected: keep the closest per session (s1:0:30, s2:0:30)
                ["s1:0:30", "s2:0:30"],
                ["s1:30:60", "s2:30:60"],
            ),
            (
                "same_session_in_different_clusters_both_kept",
                # Same session in two different clusters — each cluster keeps one
                [
                    _make_segment("s1:0:30", "s1", [1.0, 0.0, 0.0]),
                    _make_segment("s1:30:60", "s1", [0.0, 1.0, 0.0]),
                ],
                [
                    Cluster(cluster_id=0, segment_ids=["s1:0:30"], size=1),
                    Cluster(cluster_id=1, segment_ids=["s1:30:60"], size=1),
                ],
                {0: [1.0, 0.0, 0.0], 1: [0.0, 1.0, 0.0]},
                # Expected: both kept, one per cluster
                ["s1:0:30", "s1:30:60"],
                [],
            ),
        ]
    )
    def test_dedup(self, _name, segments, clusters, centroids, expected_kept, expected_dropped):
        result = ClusteringResult(
            clusters=clusters,
            noise_segment_ids=[],
            labels=[0] * len(segments),
            segment_to_cluster={doc_id: c.cluster_id for c in clusters for doc_id in c.segment_ids},
        )

        deduped = _deduplicate_sessions_within_clusters(result, segments, centroids)

        all_kept = [doc_id for c in deduped.clusters for doc_id in c.segment_ids]
        assert sorted(all_kept) == sorted(expected_kept)

        for doc_id in expected_dropped:
            assert doc_id not in deduped.segment_to_cluster
            assert doc_id in deduped.noise_segment_ids

        for cluster in deduped.clusters:
            assert cluster.size == len(cluster.segment_ids)
