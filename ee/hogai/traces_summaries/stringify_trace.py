import csv
import sys
import json
from pathlib import Path
from typing import Any

import structlog

csv.field_size_limit(sys.maxsize)
logger = structlog.get_logger(__name__)


def stringify_message(message: dict[str, Any]) -> str:
    try:
        message_content = message["content"]
        message_type = message["type"]
        # Skip context messages
        if message_type == "context":
            return None
        # Skip tool messages # TODO: Decide if I need them
        if message_type == "tool":
            return None
        # Skip empty messages
        if not message_content:
            return None
        return f"{message_type}: {message_content}"
    except Exception as e:
        logger.exception(f"Error stringifying message ({e}):\n{message}")
        return None


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
    # Stringify the messages
    stringified_messages: list[str] = []
    # Iterate input first, output next
    for message in base_input_state["messages"] + base_output_state["messages"]:
        stringified_message = stringify_message(message)
        # Skip empty messages
        if not stringified_message:
            continue
        # Check that the previous message isn't identical
        if stringified_messages and stringified_messages[-1] == stringified_message:
            continue
        stringified_messages.append(stringified_message)
    # Write to file
    with open(base_stringified_messages_file_path, "w") as f:
        f.write("\n\n".join(stringified_messages))
