"""Data models for trace clustering workflow."""

from dataclasses import dataclass
from typing import Optional

from posthog.temporal.llm_analytics.trace_clustering.constants import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_K,
    DEFAULT_MAX_SAMPLES,
    DEFAULT_MIN_K,
)


@dataclass
class ClusteringInputs:
    """Input parameters for the daily trace clustering workflow."""

    team_id: int
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    max_samples: int = DEFAULT_MAX_SAMPLES
    min_k: int = DEFAULT_MIN_K
    max_k: int = DEFAULT_MAX_K
    window_start: Optional[str] = None  # RFC3339 format, overrides lookback_days
    window_end: Optional[str] = None  # RFC3339 format, overrides lookback_days


@dataclass
class Cluster:
    """A cluster of traces.

    Contains all trace IDs in the cluster. The UI can fetch
    metadata for display as needed.
    """

    cluster_id: int
    size: int
    trace_ids: list[str]


@dataclass
class ClusteringResult:
    """Result of the clustering workflow."""

    clustering_run_id: str
    team_id: int
    timestamp: str  # ISO format
    window_start: str  # ISO format
    window_end: str  # ISO format
    total_traces_analyzed: int
    sampled_traces_count: int
    optimal_k: int
    silhouette_score: float
    inertia: float
    clusters: list[Cluster]
    duration_seconds: float
