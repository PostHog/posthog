"""Explain why a Depot backend workflow failed: each failed job's step and its log lines.

Depot's own checks carry no output, and its run pages need a Depot login. The GitHub
check a PR author opens prints these lines instead.
"""

import re
import json
import subprocess
from typing import Any

RUNNER_MARKER = re.compile(r"^##\[\w+\]")
# Depot keeps up to 8,000 characters per log line. A shorter cut keeps one long line
# from filling the annotation.
MAX_LINE = 500


def message(attempt: dict[str, Any]) -> str:
    step = " ".join(f"{attempt['job_display_name']}: {attempt['error_message']}".split())
    lines = (RUNNER_MARKER.sub("", line["content"])[:MAX_LINE] for line in attempt["relevant_lines"])
    return "\n".join((step, *lines))


def escape_annotation(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def explain(org: str, workflow: str) -> list[str]:
    """Workflow commands: one error annotation per failed step, with its log lines as the message.

    The log lines come from pull request code. Escaped as annotation data, the way
    @actions/core escapes it, they stay on the annotation's line and cannot start a command.
    """
    try:
        result = subprocess.run(
            ["depot", "ci", "diagnose", "--workflow", workflow, "--org", org, "--output", "json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        messages = [message(attempt) for attempt in json.loads(result.stdout)["representative_attempts"]]
    except Exception as error:
        return [f"::warning::Cannot read the Depot failure details: {type(error).__name__}"]
    return [f"::error title=Failed on Depot::{escape_annotation(text)}" for text in messages]
