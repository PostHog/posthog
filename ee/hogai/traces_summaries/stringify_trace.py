import csv
import sys
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import numpy as np
import tiktoken
import structlog

csv.field_size_limit(sys.maxsize)
logger = structlog.get_logger(__name__)


class TraceMessagesStringifier:
    def __init__(self, trace_id: str, input_state: list[dict[str, Any]], output_state: list[dict[str, Any]]):
        self.trace_id: str = trace_id
        self.input_state: list[dict[str, Any]] = input_state
        self.output_state: list[dict[str, Any]] = output_state

    def stringify_trace_messages(self) -> list[str] | None:
        stringified_messages: list[str] = []
        # Iterate input first, output next
        # TODO: Decide if to use input state messages, or output is enough # self.input_state["messages"] +
        # Should be clear when combining conversations (right now I work with parts)
        for message in self.output_state["messages"]:
            stringified_message = self._stringify_message(message)
            # Skip empty messages
            if not stringified_message:
                continue
            # Check that the previous message isn't identical
            if stringified_messages and stringified_messages[-1] == stringified_message:
                continue
            stringified_messages.append(stringified_message)
        # If human didn't respond to any AI messages (no interaction), skip the trace
        no_interaction_found = True
        for i, message in enumerate(stringified_messages):
            if message.startswith("human:") and i > 0 and stringified_messages[i - 1].startswith("ai:"):
                no_interaction_found = False
                break
        if no_interaction_found:
            return None
        return stringified_messages

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


class TracesLoader:
    def __init__(self, traces_dir_path: Path):
        self.traces_dir_path = traces_dir_path

    def load_traces(self) -> Generator[tuple[str, dict[str, Any], dict[str, Any]], None, None]:
        # Iterate over CSV files in the traces directory
        for csv_file_path in self.traces_dir_path.glob("*.csv"):
            yield from self._load_traces_from_csv(csv_file_path)

    def _load_traces_from_csv(
        self, csv_file_path: Path
    ) -> Generator[tuple[str, dict[str, Any], dict[str, Any]], None, None]:
        """Load traces from a CSV file and yield trace IDs, input states, and output states."""
        with open(csv_file_path) as f:
            reader = csv.reader(f)
            # Skip the headers
            next(reader)
            for row in reader:
                trace_id = row[0]
                input_state_raw = row[-3]
                if not input_state_raw:
                    # Skip traces without input state
                    # TODO: Update later to include the whole conversation
                    continue
                input_state = json.loads(input_state_raw)
                output_state_raw = row[-2]
                if not output_state_raw:
                    # Skip traces without output state
                    continue
                output_state = json.loads(output_state_raw)
                yield trace_id, input_state, output_state


if __name__ == "__main__":
    base_path = Path("/Users/woutut/Documents/Code/posthog/playground/traces-summarization")
    base_assets_path = base_path / "assets"
    base_output_path = base_path / "output"
    # Ensure directories exist
    base_path.mkdir(parents=True, exist_ok=True)
    base_assets_path.mkdir(parents=True, exist_ok=True)
    base_output_path.mkdir(parents=True, exist_ok=True)
    # Prepare for stats collection
    traces_loader = TracesLoader(base_assets_path)
    traces_count = 0
    context_skipped_traces_count = 0
    size_skipped_traces_count = 0
    # Calculate tokens
    token_counts: list[int] = []
    filtered_token_counts: list[int] = []
    traces_with_heavy_token_count: list[tuple[str, int]] = []
    traces_with_light_token_count: list[tuple[str, int]] = []
    token_encoder = tiktoken.encoding_for_model("gpt-4o")
    # Load and stringify traces
    for trace_id, input_state, output_state in traces_loader.load_traces():
        traces_count += 1
        stringifier = TraceMessagesStringifier(trace_id=trace_id, input_state=input_state, output_state=output_state)
        stringified_messages = stringifier.stringify_trace_messages()
        if not stringified_messages:
            context_skipped_traces_count += 1
            continue
        stringified_messages_str = "\n\n".join(stringified_messages)
        # Calculate the number of tokens in the stringified messages
        num_tokens = len(token_encoder.encode(stringified_messages_str))
        token_counts.append(num_tokens)
        if num_tokens > 5000:
            traces_with_heavy_token_count.append((trace_id, num_tokens))
            # Skip heavy traces as they usually rely on a heavy amount of context, which is not the expected use case
            size_skipped_traces_count += 1
            continue
        # TODO: Don't generate summaries for traces that are already light
        if num_tokens < 100:
            traces_with_light_token_count.append((trace_id, num_tokens))
        filtered_token_counts.append(num_tokens)
        # Create directory for the trace files within assets
        trace_dir_path = base_output_path / trace_id
        trace_dir_path.mkdir(parents=True, exist_ok=True)
        # Write input state to file
        with open(trace_dir_path / f"{trace_id}_input_state.json", "w") as f:
            json.dump(input_state, f, indent=4)
        # Write output state to file
        with open(trace_dir_path / f"{trace_id}_output_state.json", "w") as f:
            json.dump(output_state, f, indent=4)
        # Write stringified messages to file
        with open(trace_dir_path / f"{trace_id}_stringified_messages.txt", "w") as f:
            f.write(stringified_messages_str)

    # Sort token counts
    traces_with_heavy_token_count.sort(key=lambda x: x[1], reverse=True)  # Heavy - from largest to smallest
    traces_with_light_token_count.sort(key=lambda x: x[1])  # Light - from smallest to largest
    # Base stats
    logger.info(f"Staring traces count: {traces_count}")
    logger.info(f"Context skipped traces count: {context_skipped_traces_count}")
    logger.info(f"Size skipped traces count: {size_skipped_traces_count}")
    logger.info(f"Final traces count: {traces_count - context_skipped_traces_count - size_skipped_traces_count}")
    # Token stats
    logger.info("*" * 50)
    logger.info("*" * 50)
    logger.info("*" * 50)
    logger.info("Base token stats")
    token_stats = np.array(token_counts)
    logger.info(f"Average token count: {token_stats.mean()}")
    logger.info(f"Median token count: {np.median(token_stats)}")
    logger.info(f"90th percentile token count: {np.percentile(token_stats, 90)}")
    logger.info(f"95th percentile token count: {np.percentile(token_stats, 95)}")
    logger.info(f"99th percentile token count: {np.percentile(token_stats, 99)}")
    logger.info(f"Min token count: {token_stats.min()}")
    logger.info(f"Max token count: {token_stats.max()}")
    logger.info("*" * 50)
    logger.info(f"Traces with heavy token count: {len(traces_with_heavy_token_count)}")
    logger.info(f"Traces with heavy token count: {traces_with_heavy_token_count}")
    logger.info("*" * 50)
    logger.info(f"Traces with light token count: {len(traces_with_light_token_count)}")
    logger.info(f"Traces with light token count: {traces_with_light_token_count}")
    logger.info("*" * 50)
    logger.info("*" * 50)
    logger.info("*" * 50)
    logger.info("Filtered token stats")
    filtered_token_stats = np.array(filtered_token_counts)
    logger.info(f"Average filtered token count: {filtered_token_stats.mean()}")
    logger.info(f"Median filtered token count: {np.median(filtered_token_stats)}")
    logger.info(f"90th percentile filtered token count: {np.percentile(filtered_token_stats, 90)}")
    logger.info(f"95th percentile filtered token count: {np.percentile(filtered_token_stats, 95)}")
    logger.info(f"99th percentile filtered token count: {np.percentile(filtered_token_stats, 99)}")
    logger.info(f"Min filtered token count: {filtered_token_stats.min()}")
    logger.info(f"Max filtered token count: {filtered_token_stats.max()}")
