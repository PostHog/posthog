from typing import Any, Union

from pydantic import BaseModel


class UpdateReasoning(BaseModel):
    content: str


AssistantAction = Union[UpdateReasoning]


class DispatchedAction(BaseModel):
    langgraph_node: Any
    action: AssistantAction
