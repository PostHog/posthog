"""Cluster labeling agent using LangGraph.

This module contains a fully agent-driven LangGraph agent that handles all
cluster labeling work. The agent has rich tools to explore cluster structure
and generate high-quality, distinctive labels.
"""

from posthog.temporal.llm_analytics.trace_clustering.labeling_agent.graph import run_labeling_agent

__all__ = ["run_labeling_agent"]
