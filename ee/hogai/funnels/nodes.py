from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from ee.hogai.funnels.prompts import (
    react_system_prompt,
)
from ee.hogai.funnels.toolkit import FunnelsTaxonomyAgentToolkit
from ee.hogai.taxonomy_agent.nodes import TaxonomyAgentPlannerNode, TaxonomyAgentPlannerToolsNode
from ee.hogai.utils import AssistantNode, AssistantState
from posthog.schema import VisualizationMessage


class FunnelPlannerNode(TaxonomyAgentPlannerNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        toolkit = FunnelsTaxonomyAgentToolkit(self._team)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", react_system_prompt),
            ],
            template_format="mustache",
        )
        return super()._run(state, prompt, toolkit, config=config)


class FunnelPlannerToolsNode(TaxonomyAgentPlannerToolsNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        toolkit = FunnelsTaxonomyAgentToolkit(self._team)
        return super()._run(state, toolkit, config=config)


class FunnelGeneratorNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        plan = state.get("plan") or ""
        return {
            "messages": [VisualizationMessage(plan=plan)],
        }
