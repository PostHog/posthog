"""Data models for trace clustering workflow."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from posthog.temporal.llm_analytics.trace_clustering.constants import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_K,
    DEFAULT_MAX_SAMPLES,
    DEFAULT_MIN_K,
    DEFAULT_SAMPLES_PER_CLUSTER,
)


@dataclass
class ClusteringInputs:
    """Input parameters for the daily trace clustering workflow."""

    team_id: int
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    max_samples: int = DEFAULT_MAX_SAMPLES
    min_k: int = DEFAULT_MIN_K
    max_k: int = DEFAULT_MAX_K
    samples_per_cluster: int = DEFAULT_SAMPLES_PER_CLUSTER
    window_start: Optional[str] = None  # RFC3339 format, overrides lookback_days
    window_end: Optional[str] = None  # RFC3339 format, overrides lookback_days


@dataclass
class TraceEmbedding:
    """A trace with its embedding vector and metadata."""

    trace_id: str
    embedding: list[float]
    timestamp: datetime
    summary: Optional[str] = None
    span_count: Optional[int] = None
    duration_ms: Optional[float] = None
    has_errors: Optional[bool] = None


@dataclass
class ClusterSample:
    """Representative trace sample from a cluster."""

    trace_id: str
    summary: str
    timestamp: str  # ISO format
    span_count: int
    duration_ms: float
    has_errors: bool


@dataclass
class Cluster:
    """A cluster of traces with samples and metadata."""

    cluster_id: int
    size: int
    trace_ids: list[str]
    sample_traces: list[ClusterSample]


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
