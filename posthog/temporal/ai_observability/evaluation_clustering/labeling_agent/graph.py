"""LangGraph agent entry point for evaluation cluster labeling."""

import uuid
from typing import Any

import structlog
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from posthog.llm.gateway_client import team_distinct_id
from posthog.temporal.ai_observability.clustering_agent import fill_missing_labels, get_labeling_llm
from posthog.temporal.ai_observability.evaluation_clustering.labeling_agent.prompts import (
    EVAL_CLUSTER_LABELING_SYSTEM_PROMPT,
)
from posthog.temporal.ai_observability.evaluation_clustering.labeling_agent.state import (
    ClusterEvalData,
    EvalContent,
    EvalLabelingState,
)
from posthog.temporal.ai_observability.evaluation_clustering.labeling_agent.tools import EVAL_LABELING_TOOLS
from posthog.temporal.ai_observability.llm_endpoint import build_langchain_callbacks
from posthog.temporal.ai_observability.trace_clustering.models import ClusterLabel

logger = structlog.get_logger(__name__)


def run_eval_labeling_agent(
    team_id: int,
    cluster_data: dict[int, ClusterEvalData],
    all_eval_contents: dict[str, EvalContent],
    window_start: str,
    window_end: str,
    trace_id: str = "",
    session_id: str = "",
    clustering_run_id: str = "",
    clustering_job_id: str = "",
) -> dict[int, ClusterLabel]:
    """Run the evaluation cluster labeling agent and return generated labels.

    Mirrors ``run_labeling_agent`` in the trace agent — same ReAct pattern,
    same recursion cap, same OpenAI model. The eval-specific tools, prompt,
    and state shape come from this module's siblings.

    ``window_start``/``window_end`` are the clustering-run window — forwarded
    into state so that tools doing live DB queries (``get_generation_details``)
    can pass bounds through to ClickHouse for partition pruning.
    """
    from posthog.temporal.ai_observability.trace_clustering.constants import (
        LABELING_AGENT_MODEL,
        LABELING_AGENT_RECURSION_LIMIT,
        LABELING_AGENT_TIMEOUT,
    )

    resolved_trace_id = trace_id or str(uuid.uuid4())
    resolved_session_id = session_id or resolved_trace_id
    resolved_distinct_id = team_distinct_id(team_id)
    observability_properties = {
        "team_id": str(team_id),
        "analysis_level": "evaluation",
        **({"clustering_run_id": clustering_run_id} if clustering_run_id else {}),
        **({"clustering_job_id": clustering_job_id} if clustering_job_id else {}),
    }
    llm = get_labeling_llm(
        LABELING_AGENT_MODEL,
        LABELING_AGENT_TIMEOUT,
        trace_id=resolved_trace_id,
        session_id=resolved_session_id,
        properties=observability_properties,
        distinct_id=resolved_distinct_id,
    )

    agent = create_react_agent(
        model=llm,
        tools=EVAL_LABELING_TOOLS,
        prompt=EVAL_CLUSTER_LABELING_SYSTEM_PROMPT,
        state_schema=EvalLabelingState,
    )

    initial_state: dict[str, Any] = {
        "messages": [HumanMessage(content="Please begin labeling the evaluation clusters.")],
        "team_id": team_id,
        "window_start": window_start,
        "window_end": window_end,
        "cluster_data": cluster_data,
        "all_eval_contents": all_eval_contents,
        "current_labels": {},
    }

    callbacks = build_langchain_callbacks(
        distinct_id=resolved_distinct_id,
        trace_id=resolved_trace_id,
        session_id=resolved_session_id,
        ai_product="aio_clustering",
        properties=observability_properties,
    )

    try:
        result = agent.invoke(
            initial_state,
            {"recursion_limit": LABELING_AGENT_RECURSION_LIMIT, "callbacks": callbacks},
        )
        logger.info(
            "eval_cluster_labeling_agent_completed",
            team_id=team_id,
            num_clusters=len(cluster_data),
            labels_generated=len(result.get("current_labels", {})),
        )
        labels = result.get("current_labels", {})
        return _apply_fallbacks(labels, cluster_data)
    except Exception as e:
        logger.exception(
            "eval_cluster_labeling_agent_error",
            error=str(e),
            error_type=type(e).__name__,
            team_id=team_id,
        )
        return _apply_fallbacks({}, cluster_data)


def _apply_fallbacks(
    labels: dict[int, ClusterLabel | None],
    cluster_data: dict[int, ClusterEvalData],
) -> dict[int, ClusterLabel]:
    """Adapt the shared fallback filler to the eval-specific ClusterEvalData shape."""
    return fill_missing_labels(
        labels,
        cluster_sizes={cid: data["size"] for cid, data in cluster_data.items()},
        outlier_description="- Evaluations that didn't fit other clusters\n- May include edge-case reasoning or rare verdict patterns",
        fallback_description_singular="similar evaluations",
    )
