from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ..factory import AgentModeDefinition
from ..toolkit import AgentToolkit

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


class OnboardingAgentToolkit(AgentToolkit):
    """
    Toolkit for the onboarding agent.
    This agent helps users through the product onboarding process with conversational guidance.
    """

    @property
    def tools(self) -> list[type["MaxTool"]]:
        from ee.hogai.tools import RecommendProductsTool

        return [RecommendProductsTool]


onboarding_agent = AgentModeDefinition(
    mode=AgentMode.ONBOARDING,
    mode_description="Conversational onboarding assistant that guides users through product setup.",
    toolkit_class=OnboardingAgentToolkit,
)
