"""
Factory for creating different types of AI assistants.

This module replaces the mode-based Assistant instantiation with a clean
factory pattern that creates the appropriate assistant type.
"""

from typing import Optional, Any
from uuid import UUID

from ee.hogai.assistants.base_assistant import BaseAssistant
from ee.models import Conversation
from posthog.models import Team, User
from posthog.schema import HumanMessage, MaxBillingContext


class AssistantFactory:
    """Factory for creating assistant instances."""

    @staticmethod
    def create(
        assistant_type: str,
        team: Team,
        conversation: Conversation,
        *,
        new_message: Optional[HumanMessage] = None,
        user: User,
        session_id: Optional[str] = None,
        contextual_tools: Optional[dict[str, Any]] = None,
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
        tool_call_partial_state: Optional[Any] = None,
        billing_context: Optional[MaxBillingContext] = None,
    ) -> BaseAssistant:
        """
        Create an assistant of the specified type.

        Args:
            assistant_type: Type of assistant ("main", "insights", "memory", etc.)
            team: PostHog team
            conversation: Conversation instance
            new_message: Optional new message to process
            user: User instance
            session_id: Optional session identifier
            contextual_tools: Optional contextual tools
            is_new_conversation: Whether this is a new conversation
            trace_id: Optional trace identifier
            tool_call_partial_state: Optional partial state for tool calls
            billing_context: Optional billing context

        Returns:
            BaseAssistant instance of the requested type

        Raises:
            ValueError: If assistant_type is not supported
        """
        match assistant_type:
            case "main" | "assistant":
                from ee.hogai.assistants.main_assistant import MainAssistant

                return MainAssistant(
                    team=team,
                    conversation=conversation,
                    new_message=new_message,
                    user=user,
                    session_id=session_id,
                    contextual_tools=contextual_tools,
                    is_new_conversation=is_new_conversation,
                    trace_id=trace_id,
                    billing_context=billing_context,
                )

            case "insights":
                from ee.hogai.assistants.insights_assistant import InsightsAssistant

                return InsightsAssistant(
                    team=team,
                    conversation=conversation,
                    new_message=new_message,
                    user=user,
                    session_id=session_id,
                    contextual_tools=contextual_tools,
                    is_new_conversation=is_new_conversation,
                    trace_id=trace_id,
                    tool_call_partial_state=tool_call_partial_state,
                    billing_context=billing_context,
                )

            case _:
                supported_types = ["main", "assistant", "insights"]
                raise ValueError(
                    f"Unsupported assistant type: '{assistant_type}'. " f"Supported types: {', '.join(supported_types)}"
                )


# Backward compatibility helpers
def create_main_assistant(
    team: Team,
    conversation: Conversation,
    *,
    new_message: Optional[HumanMessage] = None,
    user: User,
    session_id: Optional[str] = None,
    contextual_tools: Optional[dict[str, Any]] = None,
    is_new_conversation: bool = False,
    trace_id: Optional[str | UUID] = None,
    billing_context: Optional[MaxBillingContext] = None,
) -> BaseAssistant:
    """Create a main assistant instance."""
    return AssistantFactory.create(
        "main",
        team,
        conversation,
        new_message=new_message,
        user=user,
        session_id=session_id,
        contextual_tools=contextual_tools,
        is_new_conversation=is_new_conversation,
        trace_id=trace_id,
        billing_context=billing_context,
    )


def create_insights_assistant(
    team: Team,
    conversation: Conversation,
    *,
    new_message: Optional[HumanMessage] = None,
    user: User,
    session_id: Optional[str] = None,
    contextual_tools: Optional[dict[str, Any]] = None,
    is_new_conversation: bool = False,
    trace_id: Optional[str | UUID] = None,
    tool_call_partial_state: Optional[Any] = None,
    billing_context: Optional[MaxBillingContext] = None,
) -> BaseAssistant:
    """Create an insights assistant instance."""
    return AssistantFactory.create(
        "insights",
        team,
        conversation,
        new_message=new_message,
        user=user,
        session_id=session_id,
        contextual_tools=contextual_tools,
        is_new_conversation=is_new_conversation,
        trace_id=trace_id,
        tool_call_partial_state=tool_call_partial_state,
        billing_context=billing_context,
    )
