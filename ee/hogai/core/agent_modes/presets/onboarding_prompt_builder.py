from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from ee.hogai.core.agent_modes.presets.onboarding_prompts import (
    ONBOARDING_APPROACH_PROMPT,
    ONBOARDING_EXAMPLES_PROMPT,
    ONBOARDING_PRODUCTS_PROMPT,
    ONBOARDING_ROLE_PROMPT,
    ONBOARDING_SYSTEM_PROMPT,
    ONBOARDING_TONE_PROMPT,
)
from ee.hogai.core.agent_modes.prompt_builder import AgentPromptBuilder
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AssistantState


class OnboardingPromptBuilder(AgentPromptBuilder):
    """Prompt builder for the onboarding agent with product discovery focus."""

    async def get_prompts(self, state: AssistantState, config: RunnableConfig) -> list[BaseMessage]:
        system_prompt = format_prompt_string(
            ONBOARDING_SYSTEM_PROMPT,
            role=ONBOARDING_ROLE_PROMPT,
            tone=ONBOARDING_TONE_PROMPT,
            products=ONBOARDING_PRODUCTS_PROMPT,
            approach=ONBOARDING_APPROACH_PROMPT,
            examples=ONBOARDING_EXAMPLES_PROMPT,
        )

        return ChatPromptTemplate.from_messages(
            [("system", system_prompt)],
            template_format="mustache",
        ).format_messages()
