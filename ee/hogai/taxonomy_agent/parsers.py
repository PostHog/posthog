import json
import re

from langchain_core.agents import AgentAction
from langchain_core.messages import AIMessage as LangchainAIMessage


class ReActParserException(ValueError):
    llm_output: str

    def __init__(self, llm_output: str):
        super().__init__(llm_output)
        self.llm_output = llm_output


class ReActParserMalformedJsonException(ReActParserException):
    pass


class ReActParserMissingActionException(ReActParserException):
    """
    The ReAct agent didn't output the "Action:" block.
    """

    pass


ACTION_LOG_PREFIX = "Action:"


def parse_react_agent_output(message: LangchainAIMessage) -> AgentAction:
    """
    A ReAct agent must output in this format:

    Some thoughts...
    Action:
    ```json
    {"action": "action_name", "action_input": "action_input"}
    ```
    """
    text = str(message.content)
    if ACTION_LOG_PREFIX not in text:
        raise ReActParserMissingActionException(text)
    found = re.compile(r"^.*?`{3}(?:json)?\n?(.*?)`{3}.*?$", re.DOTALL).search(text)
    if not found:
        # JSON not found.
        raise ReActParserMalformedJsonException(text)
    try:
        action = found.group(1).strip()
        response = json.loads(action)
        is_complete = "action" in response and "action_input" in response
    except Exception:
        # JSON is malformed or has a wrong type.
        raise ReActParserMalformedJsonException(text)
    if not is_complete:
        # JSON does not contain an action.
        raise ReActParserMalformedJsonException(text)
    parsed_action_input = response["action_input"]
    if not isinstance(response["action_input"], dict):
        parsed_action_input = str(response["action_input"])
    return AgentAction(response["action"], parsed_action_input, text)


class PydanticOutputParserException(ValueError):
    llm_output: str
    """Serialized LLM output."""
    validation_message: str
    """Pydantic validation error message."""

    def __init__(self, llm_output: str, validation_message: str):
        super().__init__(llm_output)
        self.llm_output = llm_output
        self.validation_message = validation_message
