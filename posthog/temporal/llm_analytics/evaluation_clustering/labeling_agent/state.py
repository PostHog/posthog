"""State TypedDicts for the evaluation cluster-labeling agent."""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages
from langgraph.managed import RemainingSteps

from posthog.temporal.llm_analytics.trace_clustering.models import ClusterLabel


class EvalContent(TypedDict):
    """Per-evaluation content payload passed to the labeling agent.

    Mirrors the shape the trace agent uses for ``TraceSummary`` — the agent's
    tools render these into short titles for overview passes and into full
    detail blobs when deep-diving into a cluster.

    Fields intentionally optional with sensible None handling: evaluations
    whose linked generation was retention-purged will have None operational
    fields, but the eval-specific reasoning/verdict/name are always usable.

    ``target_generation_id`` and ``evaluation_id`` are carried so the agent's
    deeper-grounding tools (``get_generation_details``, ``get_evaluator_config``)
    can resolve the corresponding $ai_generation event and Evaluation model row.
    """

    evaluation_id: str | None  # $ai_evaluation_id — links to the Evaluation model row
    evaluation_name: str | None  # $ai_evaluation_name
    verdict: str  # "pass" | "fail" | "n/a" | "unknown" — derived from result + applicable
    reasoning: str | None  # $ai_evaluation_reasoning
    runtime: str | None  # "llm_judge" | "hog"
    generation_model: str | None  # Model that produced the output being judged
    is_error: bool | None
    judge_cost_usd: float | None  # Only populated for llm_judge
    target_generation_id: str | None  # $ai_target_event_id on the eval — the linked $ai_generation uuid


class EvalMetadata(TypedDict):
    """Per-item metadata for an eval within a cluster.

    Same fields as the trace agent's ``TraceMetadata`` so both agents can share
    the same ``fill_missing_labels`` and cluster-building logic shape.
    """

    eval_id: str  # $ai_evaluation event uuid — also the embedding document_id
    title: str  # Short "{evaluator_name}: {verdict}" rendered at agent time
    rank: int  # 1 = closest to centroid
    distance_to_centroid: float
    x: float
    y: float


class ClusterEvalData(TypedDict):
    """All eval items that belong to one cluster, plus its centroid location.

    Analogous to ``ClusterTraceData`` — just with eval IDs instead of trace IDs.
    """

    cluster_id: int
    size: int
    centroid_x: float
    centroid_y: float
    evals: dict[str, EvalMetadata]  # keyed by eval_id


class EvalLabelingState(TypedDict):
    """LangGraph state for the evaluation labeling agent."""

    messages: Annotated[list, add_messages]
    remaining_steps: RemainingSteps

    team_id: int
    # The clustering-run window that bounded the metadata fetch. Tools that do
    # live DB queries (``get_generation_details``) pass these through so
    # ClickHouse can prune date partitions instead of scanning the whole team.
    window_start: str  # ISO 8601
    window_end: str  # ISO 8601
    cluster_data: dict[int, ClusterEvalData]  # cluster_id -> cluster info
    all_eval_contents: dict[str, EvalContent]  # eval_id -> full content

    current_labels: dict[int, ClusterLabel | None]
