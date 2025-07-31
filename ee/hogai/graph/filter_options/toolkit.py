from typing import TypeVar
from pydantic import BaseModel, Field
from ee.hogai.graph.taxonomy import TaxonomyAgentToolkit

OutputType = TypeVar("OutputType", bound=BaseModel)
ToolInputType = TypeVar("ToolInputType", bound=BaseModel)


def create_final_answer_model(response_model: type[OutputType]) -> type[BaseModel]:
    """
    Create a dynamic final_answer model based on the response model from FilterProfile.
    """

    class final_answer(BaseModel):
        """
        Use this tool to finalize the filter options answer.
        You MUST use this tool ONLY when you have all the information you need to build the filter.
        If you don't have all the information you need, use the `ask_user_for_help` tool to ask the user for clarification.
        """

        data: response_model = Field(description="Complete filter object as defined in the prompts")

    return final_answer


class FilterOptionsToolkit(TaxonomyAgentToolkit[ToolInputType]):
    def __init__(self, team):
        super().__init__(team=team)

    def handle_tools(self, tool_name: str, tool_input: ToolInputType) -> tuple[str, str]:
        """Handle tool execution and return (tool_id, result)."""
        return super().handle_tools(tool_name, tool_input)

    def _generate_properties_output(self, props: list[tuple[str, str | None, str | None]]) -> str:
        """
        Override parent implementation to use YAML format instead of XML.
        """
        return self._generate_properties_yaml(props)
