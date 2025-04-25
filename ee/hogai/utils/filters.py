from ee.hogai.utils.types import AssistantMessage, AssistantMessageUnion
from posthog.schema import AssistantToolCallMessage


def should_output_assistant_message(candidate_message: AssistantMessageUnion) -> bool:
    """
    This is used to filter out messages that are not useful for the user.
    Filter out tool calls without a UI payload and empty assistant messages.
    """
    if isinstance(candidate_message, AssistantToolCallMessage) and candidate_message.ui_payload is None:
        return False

    if isinstance(candidate_message, AssistantMessage) and not candidate_message.content:
        return False

    return True
