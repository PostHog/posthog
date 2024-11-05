from abc import abstractmethod

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from ee.hogai.taxonomy_agent.toolkit import TaxonomyAgentTool, TaxonomyAgentToolkit
from ee.hogai.trends.prompts import (
    react_pydantic_validation_exception_prompt,
)
from ee.hogai.utils import (
    AssistantNode,
    AssistantState,
)


class TaxonomyAgentNode(AssistantNode):
    @property
    @abstractmethod
    def _toolkit(self) -> TaxonomyAgentToolkit:
        raise NotImplementedError


class TaxonomyAgentToolsNode(TaxonomyAgentNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        toolkit = self._toolkit
        intermediate_steps = state.get("intermediate_steps") or []
        action, _ = intermediate_steps[-1]

        try:
            input = TaxonomyAgentTool.model_validate({"name": action.tool, "arguments": action.tool_input}).root
        except ValidationError as e:
            observation = (
                ChatPromptTemplate.from_template(react_pydantic_validation_exception_prompt, template_format="mustache")
                .format_messages(exception=e.errors(include_url=False))[0]
                .content
            )
            return {"intermediate_steps": [*intermediate_steps[:-1], (action, str(observation))]}

        # The plan has been found. Move to the generation.
        if input.name == "final_answer":
            return {
                "plan": input.arguments,
                "intermediate_steps": None,
            }

        output = ""
        if input.name == "retrieve_event_properties":
            output = toolkit.retrieve_event_properties(input.arguments)
        elif input.name == "retrieve_event_property_values":
            output = toolkit.retrieve_event_property_values(input.arguments.event_name, input.arguments.property_name)
        elif input.name == "retrieve_entity_properties":
            output = toolkit.retrieve_entity_properties(input.arguments)
        elif input.name == "retrieve_entity_property_values":
            output = toolkit.retrieve_entity_property_values(input.arguments.entity, input.arguments.property_name)
        else:
            output = toolkit.handle_incorrect_response(input.arguments)

        return {"intermediate_steps": [*intermediate_steps[:-1], (action, output)]}

    def router(self, state: AssistantState):
        if state.get("plan") is not None:
            return "next"
        return "continue"
