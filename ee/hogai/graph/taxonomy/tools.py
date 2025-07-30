from typing import Literal
from pydantic import BaseModel, Field


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
