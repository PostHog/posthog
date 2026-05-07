"""LangGraph cluster-labeling agent for evaluation-level clustering.

Structurally parallel to ``trace_clustering.labeling_agent``: ReAct agent with
tools over an injected state. The level-specific pieces (state shape, tool
domain, prompt) live here; the shared ChatOpenAI setup and fallback filler come
from ``posthog.temporal.llm_analytics.clustering_agent``.
"""

from posthog.temporal.llm_analytics.evaluation_clustering.labeling_agent.graph import run_eval_labeling_agent

__all__ = ["run_eval_labeling_agent"]
