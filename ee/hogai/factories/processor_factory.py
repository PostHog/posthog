"""
Factory for creating update processors.

This module provides a factory for creating graph-specific update processors
without creating circular import dependencies.
"""

from posthog.models import Team, User


class UpdateProcessorFactory:
    """Factory for creating update processors."""

    @staticmethod
    def create_insights_processor(team: Team, user: User):
        """Create an insights update processor."""
        from ee.hogai.processors.insights_update_processor import InsightsUpdateProcessor

        return InsightsUpdateProcessor(team, user)

    @staticmethod
    def create_assistant_processor(team: Team, user: User):
        """Create an assistant update processor."""
        from ee.hogai.processors.assistant_update_processor import AssistantUpdateProcessor

        return AssistantUpdateProcessor(team, user)
