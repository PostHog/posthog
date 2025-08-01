"""
State definitions for different graph types.

This package contains graph-specific state classes that replace the monolithic AssistantState.
"""

from .graph_states import (
    BaseGraphState,
    AssistantGraphState,
    InsightsGraphState,
    PartialAssistantGraphState,
    PartialInsightsGraphState,
)

__all__ = [
    "BaseGraphState",
    "AssistantGraphState",
    "InsightsGraphState",
    "PartialAssistantGraphState",
    "PartialInsightsGraphState",
]
