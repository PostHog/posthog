import csv
import sys
import json
from pathlib import Path
from typing import Any

import structlog

csv.field_size_limit(sys.maxsize)
logger = structlog.get_logger(__name__)


class TraceMessagesStringifier:
    def __init__(self, input_state: list[dict[str, Any]], output_state: list[dict[str, Any]]):
        self.input_state: list[dict[str, Any]] = input_state
        self.output_state: list[dict[str, Any]] = output_state

    def stringify_trace_messages(self) -> list[str]:
        stringified_messages: list[str] = []
        # Iterate input first, output next
        for message in self.input_state["messages"] + self.output_state["messages"]:
            stringified_message = self._stringify_message(message)
            # Skip empty messages
            if not stringified_message:
                continue
            # Check that the previous message isn't identical
            if stringified_messages and stringified_messages[-1] == stringified_message:
                continue
            stringified_messages.append(stringified_message)
        return stringified_messages

    @staticmethod
    def _stringify_answer(message: dict[str, Any]) -> str:
        answer_kind = message["answer"]["kind"]
        message_content = f"*AI displayed a {answer_kind}*"
        message_type = "ai/answer"
        return f"{message_type}: {message_content}"

    @staticmethod
    def _stringify_ai_message(message: dict[str, Any]) -> str:
        message_content = message["content"]
        tools_called = []
        for tc in message.get("tool_calls") or []:
            if tc.get("type") != "tool_call":
                continue
            tools_called.append(tc.get("name"))
        if tools_called:
            tool_content = f"*AI called tools: {', '.join(tools_called)}*"
            message_content += f" {tool_content}" if message_content else tool_content
        return f"ai: {message_content}"

    @staticmethod
    def _stringify_tool_message(message: dict[str, Any]) -> str | None:
        # Keep navigation messages
        if message.get("ui_payload") and message.get("ui_payload").get("navigate"):
            return f"ai/navigation: *{message['content']}*"
        # TODO: Decide how to catch errors as they aren't marked as errors in the trace
        return None

    @staticmethod
    def _stringify_human_message(message: dict[str, Any]) -> str | None:
        message_content = message["content"]
        if not message_content:
            return None
        return f"human: {message_content}"

    def _stringify_message(self, message: dict[str, Any]) -> str | None:
        try:
            # Answers
            if message.get("answer"):
                return self._stringify_answer(message)
            # Messages
            message_type = message["type"]
            if message_type == "ai":
                return self._stringify_ai_message(message)
            if message_type == "human":
                return self._stringify_human_message(message)
            if message_type == "context":  # Skip context messages
                return None
            if message_type == "tool":  # Decide if to keep tool messages
                return self._stringify_tool_message(message)
            # Ignore other message types
        except Exception as e:
            logger.exception(f"Error stringifying message ({e}):\n{message}")
            return None

    # def stringify_message(self, message: dict[str, Any]) -> str:
    #     try:
    #         # If LLM generated an asnwer - list a type of the answer
    #         if message.get("answer"):
    #             answer_kind = message["answer"]["kind"]
    #             message_content = f"*AI displayed a {answer_kind}*"
    #             message_type = "ai/answer"


if __name__ == "__main__":
    # Get data for the trace from the CSV and load into JSON
    base_assets_path = "/Users/woutut/Documents/Code/posthog/playground/traces-summarization/"
    base_trace_id = "6e4c8620-1a34-4d4d-948a-515062b5b941"
    base_trace_file_path = Path(base_assets_path, f"{base_trace_id}.csv")
    base_output_state_file_path = Path(base_assets_path, f"{base_trace_id}_output_state.json")
    base_input_state_file_path = Path(base_assets_path, f"{base_trace_id}_input_state.json")
    base_stringified_messages_file_path = Path(base_assets_path, f"{base_trace_id}_stringified_messages.txt")
    base_output_state = base_input_state = None
    with open(
        base_trace_file_path,
    ) as f:
        reader = csv.reader(f)
        # Skip the headers
        next(reader)
        for row in reader:
            base_output_state = json.loads(row[-2])
            base_input_state = json.loads(row[-3])
            # Working with the first row, for now
            break
    with open(base_output_state_file_path, "w") as f:
        json.dump(base_output_state, f, indent=4)
    with open(base_input_state_file_path, "w") as f:
        json.dump(base_input_state, f, indent=4)
    # Stringify messages
    stringifier = TraceMessagesStringifier(input_state=base_input_state, output_state=base_output_state)
    strinfied_trace_messages = stringifier.stringify_trace_messages()
    # Write to file
    with open(base_stringified_messages_file_path, "w") as f:
        f.write("\n\n".join(strinfied_trace_messages))
