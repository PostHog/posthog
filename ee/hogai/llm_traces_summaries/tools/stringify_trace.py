from typing import Any

import tiktoken
import structlog

from posthog.schema import LLMTrace

from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)


class LLMTracesSummarizerStringifier:
    def __init__(self, team: Team):
        self._team = team
        self._token_encoder = tiktoken.encoding_for_model("gpt-4o")
        self._stringified_trace_max_tokens = 5000

    def stringify_traces(self, traces_chunk: list[LLMTrace]) -> dict[str, str]:
        stringified_traces: dict[str, str] = {}
        for trace in traces_chunk:
            stringified_trace = self._stringify_trace_messages(trace)
            if not stringified_trace:
                continue
            stringified_traces[trace.id] = stringified_trace
        return stringified_traces

    def _stringify_trace_messages(self, trace: LLMTrace) -> str | None:
        stringified_messages: list[str] = []
        # TODO: Iterate full conversations (traces combined) instead of just traces, as it leads to duplicates
        messages = trace.outputState.get("messages") if trace.outputState else []
        for message in messages:
            stringified_message = self.stringify_message(message=message, trace_id=trace.id)
            # Skip empty messages
            if not stringified_message:
                continue
            # Check that the previous message isn't identical
            if stringified_messages and stringified_messages[-1] == stringified_message:
                continue
            stringified_messages.append(stringified_message)
        # If no messages, skip the trace
        if not stringified_messages:
            return None
        # If human didn't respond to any AI messages (no interaction), skip the trace
        no_interaction_found = True
        for i, message in enumerate(stringified_messages):
            if message.startswith("human") and i > 0 and stringified_messages[i - 1].startswith("ai"):
                no_interaction_found = False
                break
        if no_interaction_found:
            return None
        # Combine into string
        stringified_messages_str = "\n\n".join(stringified_messages)
        # Check if the trace is too long for summarization
        num_tokens = len(self._token_encoder.encode(stringified_messages_str))
        if num_tokens > self._stringified_trace_max_tokens:
            logger.warning(
                f"Trace {trace.id} from team {self._team.id} stringified version is too long ({num_tokens} tokens > {self._stringified_trace_max_tokens})"
                "for summarization when summarizing LLM traces, skipping"
            )
            return None
        return stringified_messages_str

    @staticmethod
    def _stringify_answer(message: dict[str, Any]) -> str | None:
        answer_kind = message["answer"]["kind"]
        message_content = f"*AI displayed a {answer_kind}*"
        if not message_content:
            return None
        return f"ai/answer: {message_content}"

    @staticmethod
    def _stringify_ai_message(message: dict[str, Any]) -> str | None:
        message_content = message["content"]
        tools_called = []
        for tc in message.get("tool_calls") or []:
            if tc.get("type") != "tool_call":
                continue
            tools_called.append(tc.get("name"))
        if tools_called:
            tool_content = f"*AI called tools: {', '.join(tools_called)}*"
            message_content += f" {tool_content}" if message_content else tool_content
        if not message_content:
            return None
        return f"ai: {message_content}"

    @staticmethod
    def _stringify_tool_message(message: dict[str, Any]) -> str | None:
        # Keep navigation messages
        if (
            message.get("ui_payload")
            and isinstance(message["ui_payload"], dict)
            and message["ui_payload"].get("navigate")
        ):
            return f"ai/navigation: *{message['content']}*"
        # TODO: Decide how to catch errors as they aren't marked as errors in the trace
        return None

    @staticmethod
    def _stringify_human_message(message: dict[str, Any]) -> str | None:
        message_content = message["content"]
        if not message_content:
            return None
        return f"human: {message_content}"

    def stringify_message(self, message: dict[str, Any], trace_id: str) -> str | None:
        message_type = message.get("type")
        if not message_type:
            logger.warning(
                f"Message {message.get('id')} for trace {trace_id} from team {self._team.id} has no type, skipping"
            )
            return None
        try:
            # Answers
            if message.get("answer"):
                return self._stringify_answer(message)
            # Messages
            if message_type == "ai":
                return self._stringify_ai_message(message)
            if message_type == "human":
                return self._stringify_human_message(message)
            if message_type == "context":  # Skip context messages
                return None
            if message_type == "tool":  # Decide if to keep tool messages
                return self._stringify_tool_message(message)
            # Ignore other message types
            # TODO: Decide if there's a need for other message types
            return None
        except Exception as err:
            logger.exception(
                f"Error stringifying message {message_type} ({err}) for trace {trace_id} from team {self._team.id}:\n{message}",
                error=str(err),
            )
            return None
