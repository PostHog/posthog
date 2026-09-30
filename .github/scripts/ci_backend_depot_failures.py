"""Read why a Depot backend workflow failed: each failed job's step and its log lines.

Depot's own checks carry no output, and its run pages need a Depot login. The GitHub
check a PR author opens prints these lines instead.
"""

import re
import json
import subprocess
from dataclasses import dataclass

RUNNER_MARKER = re.compile(r"^##\[\w+\]")
# Depot allows 8,000 characters per log line.
MAX_LINE = 500


@dataclass(frozen=True)
class Failure:
    step: str
    log_lines: tuple[str, ...]


def read_failures(org: str, workflow: str) -> list[Failure]:
    result = subprocess.run(
        ["depot", "ci", "diagnose", "--workflow", workflow, "--org", org, "--output", "json"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return [
        Failure(
            step=" ".join(f"{attempt['job_display_name']}: {attempt['error_message']}".split()),
            log_lines=tuple(RUNNER_MARKER.sub("", line["content"])[:MAX_LINE] for line in attempt["relevant_lines"]),
        )
        for attempt in json.loads(result.stdout)["representative_attempts"]
    ]


def render(failures: list[Failure]) -> list[str]:
    """One error annotation per failure, with its log lines in the message.

    The log lines come from pull request code. Escaped as annotation data, the way
    @actions/core escapes it, they stay on the annotation's line and cannot start a command.
    """
    return [
        "::error title=Failed on Depot::"
        + "\n".join((failure.step, *failure.log_lines)).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        for failure in failures
    ]
