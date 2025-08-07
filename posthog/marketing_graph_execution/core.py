"""
Simple graph execution for marketing analysis.
"""

import uuid
from typing import Any
from typing_extensions import TypedDict


class StepContext(TypedDict, total=False):
    """Shared context for marketing analysis."""

    execution_id: str
    input_data: dict[str, Any]
    processing_state: dict[str, Any]
    final_output: dict[str, Any]


class MarketingGraphExecutor:
    """Simple graph executor - kept for backward compatibility."""

    def __init__(self):
        self.execution_id = str(uuid.uuid4())

    def execute_with_streaming(self, initial_data: dict[str, Any]):
        """Execute with streaming events using the proper graph system."""
        from .graph import create_marketing_analysis_graph

        graph = create_marketing_analysis_graph()

        # Delegate to the proper graph execution engine
        yield from graph.execute_with_streaming(initial_data)
