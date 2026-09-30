"""Read why a Depot backend workflow failed: each failed job's step and its log lines.

Depot's own checks carry no output, and its run pages need a Depot login. The GitHub
check a PR author opens prints these lines instead.
"""

import re
import json
import secrets
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


def escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def render(failures: list[Failure]) -> list[str]:
    """Workflow log lines: one error annotation per failure, then the log lines as inert text.

    The log lines come from pull request code. stop-commands keeps any `::` command in them
    from running.
    """
    if not failures:
        return []
    token = secrets.token_hex(16)
    return [
        *(f"::error title=Failed on Depot::{escape(failure.step)}" for failure in failures),
        f"::stop-commands::{token}",
        *(line for failure in failures for line in ("", failure.step, *failure.log_lines)),
        f"::{token}::",
    ]
