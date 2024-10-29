import json
import re

from langchain_core.agents import AgentAction


class ReActParserException(ValueError):
    llm_output: str

    def __init__(self, llm_output: str):
        super().__init__(llm_output)
        self.llm_output = llm_output


class ReActParserMalformedJsonException(ReActParserException):
    pass


class ReActParserMissingActionOrArgsException(ReActParserException):
    pass


def parse_react_agent_output(text: str) -> AgentAction:
    found = re.compile(r"^.*?`{3}(?:json)?\n?(.*?)`{3}.*?$", re.DOTALL).search(text)
    if not found:
        # JSON not found.
        raise ReActParserMalformedJsonException(text)
    action = found.group(1).strip()
    try:
        response = json.loads(action)
        is_complete = "action" in response and "action_input" in response
    except Exception:
        # JSON is malformed or has a wrong type.
        raise ReActParserMalformedJsonException(text)
    if not is_complete:
        # JSON does not contain an action.
        raise ReActParserMissingActionOrArgsException(text)
    return AgentAction(response["action"], response.get("action_input", {}), text)
