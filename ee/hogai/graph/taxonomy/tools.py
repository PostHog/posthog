from typing import Literal
from pydantic import BaseModel, Field, create_model

from .types import OutputType


class retrieve_event_properties(BaseModel):
    """
    Use this tool to retrieve the property names of an event. You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

    - **Try other events** if the tool doesn't return any properties.
    - **Prioritize properties that are directly related to the context or objective of the user's query.**
    - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.
    """

    event_name: str = Field(..., description="The name of the event that you want to retrieve properties for.")


class retrieve_action_properties(BaseModel):
    """
    Use this tool to retrieve the property names of an action. You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

    - **Try other actions or events** if the tool doesn't return any properties.
    - **Prioritize properties that are directly related to the context or objective of the user's query.**
    - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.
    """

    action_id: int = Field(..., description="The ID of the action that you want to retrieve properties for.")


class retrieve_entity_properties(BaseModel):
    """
    Use this tool to retrieve property names for a property group (entity). You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

    - **Infer the property groups from the user's request.**
    - **Try other entities** if the tool doesn't return any properties.
    - **Prioritize properties that are directly related to the context or objective of the user's query.**
    - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.
    """

    entity: Literal["person", "session"] = Field(
        ..., description="The type of the entity that you want to retrieve properties for."
    )


class retrieve_event_property_values(BaseModel):
    """
    Use this tool to retrieve the property values for an event. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.
    """

    event_name: str = Field(..., description="The name of the event that you want to retrieve values for.")
    property_name: str = Field(..., description="The name of the property that you want to retrieve values for.")


class retrieve_action_property_values(BaseModel):
    """
    Use this tool to retrieve the property values for an action. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.
    """

    action_id: int = Field(..., description="The ID of the action that you want to retrieve values for.")
    property_name: str = Field(..., description="The name of the property that you want to retrieve values for.")


class retrieve_entity_property_values(BaseModel):
    """
    Use this tool to retrieve property values for a property name. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.
    """

    entity: Literal["person", "session"] = Field(
        ..., description="The type of the entity that you want to retrieve properties for."
    )
    property_name: str = Field(..., description="The name of the property that you want to retrieve values for.")


class ask_user_for_help(BaseModel):
    """
    Use this tool to ask a question to the user. Your question must be concise and clear.
    """

    request: str = Field(..., description="The question you want to ask the user.")


def get_dynamic_entity_tools(team_group_types: list[str]):
    """Create dynamic Pydantic models with correct entity types for this team."""
    # Create Literal type with actual entity names
    DynamicEntityLiteral = Literal["person", "session", *team_group_types]  # type: ignore
    # Create dynamic retrieve_entity_properties model
    retrieve_entity_properties_dynamic = create_model(
        "retrieve_entity_properties",
        entity=(
            DynamicEntityLiteral,
            Field(..., description="The type of the entity that you want to retrieve properties for."),
        ),
        __doc__="""
            Use this tool to retrieve property names for a property group (entity). You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

            - **Infer the property groups from the user's request.**
            - **Try other entities** if the tool doesn't return any properties.
            - **Prioritize properties that are directly related to the context or objective of the user's query.**
            - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.
            """,
    )
    # Create dynamic retrieve_entity_property_values model
    retrieve_entity_property_values_dynamic = create_model(
        "retrieve_entity_property_values",
        entity=(
            DynamicEntityLiteral,
            Field(..., description="The type of the entity that you want to retrieve properties for."),
        ),
        property_name=(
            str,
            Field(..., description="The name of the property that you want to retrieve values for."),
        ),
        __doc__="""
            Use this tool to retrieve property values for a property name. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.
            """,
    )

    return retrieve_entity_properties_dynamic, retrieve_entity_property_values_dynamic


def create_final_answer_model(response_model: type[OutputType]) -> type[BaseModel]:
    """
    Create a dynamic final_answer model based on the response model from the prompt.
    """

    class final_answer(BaseModel):
        """
        Use this tool to finalize the answer.
        You MUST use this tool ONLY when you have all the information you need to build the answer.
        If you don't have all the information you need, use the `ask_user_for_help` tool to ask the user for clarification.
        """

        data: response_model = Field(description="Complete response object as defined in the prompts")  # type: ignore[valid-type]

    return final_answer
