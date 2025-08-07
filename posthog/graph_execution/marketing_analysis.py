"""
Simple marketing analysis functions.
"""

from .core import GraphExecutor


def create_marketing_analysis_graph(**kwargs) -> GraphExecutor:
    """Create a simple marketing analysis executor."""
    return GraphExecutor()


def create_competitor_analysis_graph(**kwargs) -> GraphExecutor:
    """Create a simple competitor analysis executor."""
    return GraphExecutor()


def create_recommendations_graph(**kwargs) -> GraphExecutor:
    """Create a simple recommendations executor."""
    return GraphExecutor()
