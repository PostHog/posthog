from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.tools.todo_write import POSITIVE_TODO_EXAMPLES

from ..factory import AgentModeDefinition
from ..toolkit import AgentToolkit

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


class OnboardingAgentToolkit(AgentToolkit):
    """
    Toolkit for the onboarding agent.
    This agent helps users through the product onboarding process with conversational guidance.
    """

    POSITIVE_TODO_EXAMPLES = [*POSITIVE_TODO_EXAMPLES]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        # Onboarding agent doesn't need any tools, it's primarily conversational
        # and guides users through the onboarding steps
        return []


onboarding_agent = AgentModeDefinition(
    mode=AgentMode.ONBOARDING,
    mode_description="Conversational onboarding assistant that guides users through product setup.",
    toolkit_class=OnboardingAgentToolkit,
)
