#!/usr/bin/env python3
from __future__ import annotations

import sys
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LARGE_CONTEXT_TOKENS = 300_000
PROMPT_CACHE_COLD_AFTER = timedelta(hours=1)
TRANSCRIPT_TAIL_BYTES = 4 * 1024 * 1024


def last_response(transcript: Path) -> dict[str, Any] | None:
    with transcript.open("rb") as file:
        file.seek(0, 2)
        file.seek(max(0, file.tell() - TRANSCRIPT_TAIL_BYTES))
        lines = file.read().splitlines()
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("type") == "assistant" and (record.get("message") or {}).get("usage"):
            return record
    return None


def context_tokens(usage: dict[str, Any]) -> int:
    return sum(
        usage.get(key) or 0 for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    )


def current_branch(cwd: str) -> str:
    result = subprocess.run(
        ["git", "-C", cwd, "branch", "--show-current"], capture_output=True, text=True, timeout=2, check=False
    )
    return result.stdout.strip()


def idle_duration(idle: timedelta) -> str:
    if idle >= timedelta(days=2):
        return f"{idle.days} days"
    return f"{idle // timedelta(hours=1)} hours"


def resume_hints(event: dict[str, Any], now: datetime) -> list[str]:
    if event.get("source") not in ("resume", "fork"):
        return []
    response = last_response(Path(event["transcript_path"]))
    if response is None:
        return []

    hints = []
    tokens = context_tokens(response["message"]["usage"])
    idle = now - datetime.fromisoformat(response["timestamp"].replace("Z", "+00:00"))
    if tokens >= LARGE_CONTEXT_TOKENS and idle >= PROMPT_CACHE_COLD_AFTER:
        hints.append(
            f"This session holds about {tokens // 1000}k tokens of context and was idle for {idle_duration(idle)}, "
            "so its prompt cache has expired and the next message re-sends all of it without the cache discount. "
            "Run /compact first, or start a new session if the next task is unrelated."
        )

    previous_branch = response.get("gitBranch") or ""
    branch = current_branch(event.get("cwd") or ".")
    if previous_branch and branch and previous_branch != branch:
        hints.append(
            f"This session last worked on {previous_branch}, and the checkout is now on {branch}. "
            "One session per pull request keeps context small, so start a new session for unrelated work."
        )
    return hints


def main() -> None:
    try:
        hints = resume_hints(json.load(sys.stdin), datetime.now(timezone.utc))  # noqa: UP017 — the hook may run on a system Python older than 3.11
    except Exception:
        return
    if hints:
        sys.stdout.write(json.dumps({"systemMessage": "\n\n".join(hints)}) + "\n")


if __name__ == "__main__":
    main()
