"""
PostHog AI Assistant Package

This package provides the AI assistant system for PostHog, featuring:
- Graph-specific assistant types (main assistant, insights assistant)
- Modular state management with specialized states per graph type
- Update processors for handling streaming messages
- Factory patterns for creating assistants and processors
- Checkpoint migration system for backward compatibility

Key Components:
- assistants/: Assistant implementations (BaseAssistant, MainAssistant, InsightsAssistant)
- states/: Graph-specific state classes (AssistantGraphState, InsightsGraphState)
- processors/: Update processors for message handling
- factories/: Factory classes for creating assistants and processors
- graph/: Graph definitions and node implementations
- django_checkpointer/: Checkpoint persistence and migration
"""

# Re-export key components for backward compatibility
from .assistants import MainAssistant, InsightsAssistant, BaseAssistant
from .states import AssistantGraphState, InsightsGraphState
from .factories import AssistantFactory, UpdateProcessorFactory

__all__ = [
    "MainAssistant",
    "InsightsAssistant",
    "BaseAssistant",
    "AssistantGraphState",
    "InsightsGraphState",
    "AssistantFactory",
    "UpdateProcessorFactory",
]
