#!/usr/bin/env python3
"""Decide which CI engine runs a Backend CI event: GitHub Actions or Depot CI.

Both engines run this script from their own workflow and skip the heavy jobs
when the answer is not them, so exactly one engine runs the tests and the side
effects for a given event. GitHub Actions passes CI_BACKEND_DEPOT_PERCENT from
`vars`; Depot CI passes GITHUB_TOKEN and the script reads the variable.
"""

import os
import sys
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import IO

LABEL_FORCE_GITHUB = "ci-backend-github"
LABEL_FORCE_DEPOT = "ci-backend-depot"
PERCENT_VARIABLE = "CI_BACKEND_DEPOT_PERCENT"


@dataclass(frozen=True)
class Decision:
    route: str
    reason: str


def parse_percent(raw: str | None) -> int:
    value = raw.strip() if raw is not None else ""
    if not value.isascii() or not value.isdecimal():
        return 0
    try:
        return min(int(value), 100)
    except ValueError:
        return 0


def decide(
    platform: str,
    event: str,
    percent: int,
    pr_number: int | None,
    labels: list[str],
    is_fork: bool,
    is_draft: bool,
) -> Decision:
    if platform not in ("github", "depot"):
        raise ValueError(f"unknown platform {platform!r}")
    if event in ("workflow_dispatch", "api"):
        return Decision(platform, "manual runs stay on the engine that received them")
    if event != "pull_request":
        if platform == "depot" and percent == 0:
            return Decision("github", f"{event} runs on Depot only while {PERCENT_VARIABLE} is above 0")
        return Decision(platform, f"{event} runs on every engine that primes its own cache")
    if LABEL_FORCE_GITHUB in labels:
        return Decision("github", f"label {LABEL_FORCE_GITHUB}")
    if is_fork:
        return Decision("github", "fork pull requests never run on Depot")
    if is_draft and "no-ci" in labels:
        return Decision("github", "no-ci drafts skip on GitHub Actions and run nowhere else")
    if LABEL_FORCE_DEPOT in labels:
        return Decision("depot", f"label {LABEL_FORCE_DEPOT}")
    if pr_number is None:
        return Decision("github", "no pull request number to hash")
    bucket = pr_number % 100
    if bucket < percent:
        return Decision("depot", f"bucket {bucket} < {percent}%")
    return Decision("github", f"bucket {bucket} >= {percent}%")


Opener = Callable[[urllib.request.Request], AbstractContextManager[IO[str] | IO[bytes]]]


def fetch_percent(repository: str, token: str, opener: Opener = urllib.request.urlopen) -> str | None:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/actions/variables/{PERCENT_VARIABLE}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    try:
        with opener(request) as response:
            return str(json.load(response).get("value", ""))
    except (urllib.error.URLError, ValueError, OSError) as exc:
        sys.stderr.write(f"::warning::Could not read {PERCENT_VARIABLE}: {exc}. Routing to GitHub Actions.\n")
        return None


def main() -> int:
    env = os.environ
    raw_percent = env.get("PERCENT")
    if raw_percent is None and env.get("GITHUB_TOKEN") and env.get("GITHUB_REPOSITORY"):
        raw_percent = fetch_percent(env["GITHUB_REPOSITORY"], env["GITHUB_TOKEN"])
    pr_raw = env.get("PR_NUMBER", "")
    decision = decide(
        platform=env["PLATFORM"],
        event=env.get("EVENT", ""),
        percent=parse_percent(raw_percent),
        pr_number=int(pr_raw) if pr_raw.isdigit() else None,
        labels=json.loads(env.get("LABELS") or "[]") or [],
        is_fork=env.get("IS_FORK", "false") == "true",
        is_draft=env.get("IS_DRAFT", "false") == "true",
    )
    sys.stdout.write(f"::notice::Backend CI route: {decision.route} ({decision.reason})\n")
    output_path = env.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"route={decision.route}\nreason={decision.reason}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
