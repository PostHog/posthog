"""Graph nodes for the cluster labeling agent."""

import os
import json
from typing import Any, Literal

from django.conf import settings

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from posthog.cloud_utils import is_cloud
from posthog.temporal.llm_analytics.trace_clustering.labeling_agent.prompts import CLUSTER_LABELING_SYSTEM_PROMPT
from posthog.temporal.llm_analytics.trace_clustering.labeling_agent.state import ClusterLabelingState
from posthog.temporal.llm_analytics.trace_clustering.labeling_agent.tools import LABELING_TOOLS, execute_tool
from posthog.temporal.llm_analytics.trace_clustering.models import ClusterLabel

logger = structlog.get_logger(__name__)


def get_anthropic_client(model: str, timeout: float = 300.0) -> ChatAnthropic:
    """Create an Anthropic chat client for the labeling agent."""
    if not settings.DEBUG and not is_cloud():
        raise Exception("AI features are only available in PostHog Cloud")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise Exception("Anthropic API key is not configured")

    return ChatAnthropic(
        model=model,
        api_key=api_key,
        timeout=timeout,
        max_retries=2,
    )


def agent_node(state: ClusterLabelingState, config: dict | None = None) -> dict[str, Any]:
    """Main agent reasoning node.

    This node invokes the LLM with tools bound and returns the LLM's response.
    The response may contain tool calls that will be executed by the tools node.
    """
    from posthog.temporal.llm_analytics.trace_clustering.constants import LABELING_AGENT_MODEL, LABELING_AGENT_TIMEOUT

    # Check iteration limit
    if state["iterations"] >= state["max_iterations"]:
        logger.warning(
            "cluster_labeling_agent_max_iterations_reached",
            iterations=state["iterations"],
            max_iterations=state["max_iterations"],
        )
        # Force finalization by returning a message indicating we're done
        return {
            "messages": [
                AIMessage(
                    content="Maximum iterations reached. Finalizing with current labels.",
                    tool_calls=[{"name": "finalize_labels", "args": {}, "id": "max_iter_finalize"}],
                )
            ],
            "iterations": state["iterations"] + 1,
        }

    # Get LLM client with tools bound
    llm = get_anthropic_client(LABELING_AGENT_MODEL, LABELING_AGENT_TIMEOUT)
    llm_with_tools = llm.bind_tools(LABELING_TOOLS)

    # Build messages for the LLM
    messages = []

    # Add system message
    messages.append(SystemMessage(content=CLUSTER_LABELING_SYSTEM_PROMPT))

    # Add conversation history from state
    for msg in state["messages"]:
        messages.append(msg)

    # If this is the first turn (no messages yet), add initial human message
    if not state["messages"]:
        messages.append(HumanMessage(content="Please begin labeling the clusters."))

    # Invoke LLM
    try:
        response = llm_with_tools.invoke(messages)
    except Exception as e:
        logger.exception(
            "cluster_labeling_agent_llm_error",
            error=str(e),
            error_type=type(e).__name__,
            team_id=state["team_id"],
        )
        # On error, force finalization
        return {
            "messages": [
                AIMessage(
                    content=f"Error occurred: {e}. Finalizing with current labels.",
                    tool_calls=[{"name": "finalize_labels", "args": {}, "id": "error_finalize"}],
                )
            ],
            "iterations": state["iterations"] + 1,
        }

    return {
        "messages": [response],
        "iterations": state["iterations"] + 1,
    }


def tools_node(state: ClusterLabelingState) -> dict[str, Any]:
    """Execute tool calls from the agent.

    This node processes tool calls from the last AI message, executes them,
    and returns tool messages with the results. It also updates state for
    tools that modify state (like set_cluster_label).
    """
    last_message = state["messages"][-1]

    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        # No tool calls to process
        return {}

    tool_messages = []
    state_updates: dict[str, Any] = {}

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_id = tool_call["id"]

        try:
            result = execute_tool(tool_name, tool_args, state)

            # Handle special cases for state-modifying tools
            if tool_name == "set_cluster_label":
                # Result is (ClusterLabel, confirmation_message)
                new_label, confirmation = result
                cluster_id = tool_args["cluster_id"]

                # Update current_labels in state
                if "current_labels" not in state_updates:
                    state_updates["current_labels"] = dict(state["current_labels"])
                state_updates["current_labels"][cluster_id] = new_label
                result_str = confirmation
            elif tool_name == "bulk_set_labels":
                # Result is (dict[int, ClusterLabel], confirmation_message)
                new_labels, confirmation = result

                # Update current_labels in state with all new labels
                if "current_labels" not in state_updates:
                    state_updates["current_labels"] = dict(state["current_labels"])
                state_updates["current_labels"].update(new_labels)
                result_str = confirmation
            elif tool_name == "finalize_labels":
                # Just return the message, routing will handle the transition
                result_str = result
            else:
                # For read-only tools, serialize the result
                result_str = json.dumps(result, indent=2, default=str)

            tool_messages.append(
                ToolMessage(
                    content=result_str,
                    tool_call_id=tool_id,
                    name=tool_name,
                )
            )

        except Exception as e:
            logger.exception(
                "cluster_labeling_agent_tool_error",
                tool_name=tool_name,
                error=str(e),
                error_type=type(e).__name__,
            )
            tool_messages.append(
                ToolMessage(
                    content=f"Error executing {tool_name}: {e}",
                    tool_call_id=tool_id,
                    name=tool_name,
                )
            )

    return {
        "messages": tool_messages,
        **state_updates,
    }


def finalize_node(state: ClusterLabelingState) -> dict[str, Any]:
    """Finalization node.

    This node is called when the agent calls finalize_labels or when
    max iterations is reached. It validates and returns the final labels.
    """
    # Ensure all clusters have labels (fill in defaults for any missing)
    final_labels = dict(state["current_labels"])

    for cluster_id in state["cluster_data"].keys():
        if cluster_id not in final_labels or final_labels[cluster_id] is None:
            # Generate default label
            cluster_size = state["cluster_data"][cluster_id]["size"]
            if cluster_id == -1:
                final_labels[cluster_id] = ClusterLabel(
                    title="Outliers",
                    description=f"- {cluster_size} traces that didn't fit other clusters\n- May include edge cases or rare patterns\n- Worth investigating individually",
                )
            else:
                final_labels[cluster_id] = ClusterLabel(
                    title=f"Cluster {cluster_id}",
                    description=f"- Contains {cluster_size} similar traces\n- Label not generated by agent",
                )

    logger.info(
        "cluster_labeling_agent_finalized",
        team_id=state["team_id"],
        num_clusters=len(final_labels),
        iterations=state["iterations"],
    )

    return {"current_labels": final_labels}


def route_after_agent(state: ClusterLabelingState) -> Literal["tools", "finalize"]:
    """Route after agent node based on tool calls.

    Returns "tools" if there are tool calls to process (except finalize_labels).
    Returns "finalize" if finalize_labels was called or no tool calls.
    """
    last_message = state["messages"][-1] if state["messages"] else None

    if not last_message or not isinstance(last_message, AIMessage):
        return "finalize"

    if not last_message.tool_calls:
        # No tool calls - agent is done (safety fallback)
        return "finalize"

    # Check if finalize_labels was called
    for tool_call in last_message.tool_calls:
        if tool_call["name"] == "finalize_labels":
            return "finalize"

    # Regular tool calls - execute them
    return "tools"
