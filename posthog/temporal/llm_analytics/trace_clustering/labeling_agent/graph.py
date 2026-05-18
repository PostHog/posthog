"""LangGraph agent for cluster labeling using create_react_agent."""

from typing import Any

import structlog
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from posthog.temporal.llm_analytics.clustering_agent import fill_missing_labels, get_labeling_llm
from posthog.temporal.llm_analytics.trace_clustering.labeling_agent.prompts import CLUSTER_LABELING_SYSTEM_PROMPT
from posthog.temporal.llm_analytics.trace_clustering.labeling_agent.state import ClusterLabelingState, ClusterTraceData
from posthog.temporal.llm_analytics.trace_clustering.labeling_agent.tools import LABELING_TOOLS
from posthog.temporal.llm_analytics.trace_clustering.models import ClusterLabel, TraceSummary

logger = structlog.get_logger(__name__)


def run_labeling_agent(
    team_id: int,
    cluster_data: dict[int, ClusterTraceData],
    all_trace_summaries: dict[str, TraceSummary],
    max_iterations: int | None = None,
) -> dict[int, ClusterLabel]:
    """Run the cluster labeling agent and return generated labels.

    Uses LangGraph's create_react_agent for a clean, prebuilt agent pattern.

    Args:
        team_id: The team ID for logging
        cluster_data: Dict mapping cluster_id to ClusterTraceData with traces
        all_trace_summaries: Dict mapping trace_id to full TraceSummary
        max_iterations: Unused (kept for API compatibility, use recursion_limit instead)

    Returns:
        Dict mapping cluster_id to ClusterLabel
    """
    from posthog.temporal.llm_analytics.trace_clustering.constants import (
        LABELING_AGENT_MODEL,
        LABELING_AGENT_RECURSION_LIMIT,
        LABELING_AGENT_TIMEOUT,
    )

    # Create LLM client
    llm = get_labeling_llm(LABELING_AGENT_MODEL, LABELING_AGENT_TIMEOUT)

    # Create the agent using prebuilt pattern
    agent = create_react_agent(
        model=llm,
        tools=LABELING_TOOLS,
        prompt=CLUSTER_LABELING_SYSTEM_PROMPT,
        state_schema=ClusterLabelingState,
    )

    # Initialize state
    initial_state: dict[str, Any] = {
        "messages": [HumanMessage(content="Please begin labeling the clusters.")],
        "team_id": team_id,
        "cluster_data": cluster_data,
        "all_trace_summaries": all_trace_summaries,
        "current_labels": {},
    }

    # Run the agent
    try:
        result = agent.invoke(
            initial_state,
            {"recursion_limit": LABELING_AGENT_RECURSION_LIMIT},
        )

        logger.info(
            "cluster_labeling_agent_completed",
            team_id=team_id,
            num_clusters=len(cluster_data),
            labels_generated=len(result.get("current_labels", {})),
        )

        # Extract labels and fill any missing
        labels = result.get("current_labels", {})
        return _apply_fallbacks(labels, cluster_data)

    except Exception as e:
        logger.exception(
            "cluster_labeling_agent_error",
            error=str(e),
            error_type=type(e).__name__,
            team_id=team_id,
        )
        # Return empty labels dict, will be filled with defaults
        return _apply_fallbacks({}, cluster_data)


def _apply_fallbacks(
    labels: dict[int, ClusterLabel | None],
    cluster_data: dict[int, ClusterTraceData],
) -> dict[int, ClusterLabel]:
    """Adapt the generic fallback filler to the trace-specific ClusterTraceData shape."""
    return fill_missing_labels(
        labels,
        cluster_sizes={cid: data["size"] for cid, data in cluster_data.items()},
        outlier_description="- Traces that didn't fit other clusters\n- May include edge cases or rare patterns",
        fallback_description_singular="similar traces",
    )
