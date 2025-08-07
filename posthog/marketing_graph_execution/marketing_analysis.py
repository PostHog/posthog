"""
Simple marketing analysis functions.
"""

from .core import MarketingGraphExecutor


def create_marketing_analysis_graph(**kwargs) -> MarketingGraphExecutor:
    """Create a simple marketing analysis executor."""
    return MarketingGraphExecutor()
