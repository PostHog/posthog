"""Dataclasses passed between MCP analytics Temporal activities."""

from dataclasses import dataclass, field
from typing import Any

from posthog.temporal.mcp_analytics.constants import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_INTENT_SAMPLES,
    DEFAULT_MAX_SPAN_SAMPLES,
)


@dataclass
class EmbeddingEmitWorkflowInputs:
    """Inputs for the workflow that emits embedding requests for intents and span text."""

    team_id: int
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    max_intent_samples: int = DEFAULT_MAX_INTENT_SAMPLES
    max_span_samples: int = DEFAULT_MAX_SPAN_SAMPLES
    embedding_model: str = DEFAULT_EMBEDDING_MODEL

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"team_id": self.team_id}


@dataclass
class EmbeddingEmitActivityInputs:
    team_id: int
    window_start: str
    window_end: str
    max_intent_samples: int
    max_span_samples: int
    embedding_model: str

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"team_id": self.team_id}


@dataclass
class EmbeddingEmitResult:
    intents_emitted: int = 0
    spans_emitted: int = 0


@dataclass
class IntentClusteringWorkflowInputs:
    """Inputs for the daily intent clustering workflow."""

    team_id: int
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    max_samples: int = DEFAULT_MAX_INTENT_SAMPLES
    embedding_model: str = DEFAULT_EMBEDDING_MODEL

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"team_id": self.team_id}


@dataclass
class IntentClusteringActivityInputs:
    team_id: int
    window_start: str
    window_end: str
    max_samples: int
    embedding_model: str

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"team_id": self.team_id}


@dataclass
class IntentStat:
    """Per-intent failure / retry signal joined from mcp_tool_call events.

    These are used both to weight clusters when scoring "gap likelihood" and to
    show users which intents are driving each candidate gap.
    """

    intent: str
    total_calls: int
    error_count: int
    empty_response_count: int
    distinct_tools_attempted: int
    dominant_tool: str
    sample_session_ids: list[str] = field(default_factory=list)

    @property
    def error_rate(self) -> float:
        return self.error_count / self.total_calls if self.total_calls else 0.0

    @property
    def empty_rate(self) -> float:
        return self.empty_response_count / self.total_calls if self.total_calls else 0.0


@dataclass
class IntentClusterMember:
    intent: str
    stat: IntentStat
    distance_to_centroid: float


@dataclass
class IntentCluster:
    cluster_id: int
    size: int
    title: str
    description: str
    gap_score: float  # 0..1 — labeler's estimate that this is a missing tool gap
    centroid: list[float]
    members: list[IntentClusterMember]
    aggregate_error_rate: float
    aggregate_empty_rate: float
    avg_distinct_tools_attempted: float


@dataclass
class IntentClusteringResult:
    clustering_run_id: str
    team_id: int
    window_start: str
    window_end: str
    num_intents_analyzed: int
    clusters: list[IntentCluster]


@dataclass
class ClusterLabel:
    """LLM-generated label for a single cluster."""

    title: str
    description: str
    gap_score: float
