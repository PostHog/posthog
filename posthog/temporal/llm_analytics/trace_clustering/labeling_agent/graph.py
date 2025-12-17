"""LangGraph StateGraph assembly for the cluster labeling agent."""

from langgraph.graph import END, StateGraph

from posthog.temporal.llm_analytics.trace_clustering.labeling_agent.nodes import (
    agent_node,
    finalize_node,
    route_after_agent,
    tools_node,
)
from posthog.temporal.llm_analytics.trace_clustering.labeling_agent.state import ClusterLabelingState, ClusterTraceData
from posthog.temporal.llm_analytics.trace_clustering.models import ClusterLabel, TraceSummary


def build_labeling_graph() -> StateGraph:
    """Build the cluster labeling agent graph.

    Graph structure:
        START → agent → (tools ↔ agent) → finalize → END

    The agent node invokes the LLM with tools. Based on tool calls:
    - If finalize_labels is called or no tool calls: route to finalize
    - Otherwise: route to tools, which executes tools then loops back to agent
    """
    graph = StateGraph(ClusterLabelingState)

    # Add nodes
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("finalize", finalize_node)

    # Set entry point
    graph.set_entry_point("agent")

    # Add edges
    # After agent, conditionally route based on tool calls
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "tools": "tools",
            "finalize": "finalize",
        },
    )

    # After tools, always go back to agent
    graph.add_edge("tools", "agent")

    # After finalize, end
    graph.add_edge("finalize", END)

    return graph


def run_labeling_agent(
    team_id: int,
    cluster_data: dict[int, ClusterTraceData],
    all_trace_summaries: dict[str, TraceSummary],
    max_iterations: int | None = None,
) -> dict[int, ClusterLabel]:
    """Run the cluster labeling agent and return generated labels.

    Args:
        team_id: The team ID for logging
        cluster_data: Dict mapping cluster_id to ClusterTraceData with traces
        all_trace_summaries: Dict mapping trace_id to full TraceSummary
        max_iterations: Maximum agent iterations (default from constants)

    Returns:
        Dict mapping cluster_id to ClusterLabel
    """
    from posthog.temporal.llm_analytics.trace_clustering.constants import (
        LABELING_AGENT_MAX_ITERATIONS,
        LABELING_AGENT_RECURSION_LIMIT,
    )

    if max_iterations is None:
        max_iterations = LABELING_AGENT_MAX_ITERATIONS

    # Build and compile graph
    graph = build_labeling_graph()
    compiled_graph = graph.compile()

    # Initialize state
    initial_state: ClusterLabelingState = {
        "team_id": team_id,
        "cluster_data": cluster_data,
        "all_trace_summaries": all_trace_summaries,
        "current_labels": {},
        "messages": [],
        "iterations": 0,
        "max_iterations": max_iterations,
    }

    # Run the graph with streaming to capture intermediate state on error
    last_state = initial_state
    try:
        for state_update in compiled_graph.stream(
            initial_state,
            {"recursion_limit": LABELING_AGENT_RECURSION_LIMIT},
            stream_mode="values",
        ):
            last_state = state_update

        # Extract labels from final state
        labels = last_state.get("current_labels", {})

        # Filter out None values and ensure all are ClusterLabel instances
        result: dict[int, ClusterLabel] = {}
        for cluster_id, label in labels.items():
            if label is not None:
                result[cluster_id] = label

        return result

    except (RecursionError, Exception):
        # On error, return whatever labels we've generated so far
        labels = last_state.get("current_labels", {})
        result: dict[int, ClusterLabel] = {}
        for cluster_id, label in labels.items():
            if label is not None:
                result[cluster_id] = label

        return result
