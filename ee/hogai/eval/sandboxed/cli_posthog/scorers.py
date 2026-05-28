"""Deterministic scorers for the ``cli_posthog`` evals.

These mirror the ``cli_mcp`` scorers, but the agent drives the **real
``posthog-cli`` binary via Bash** rather than the MCP ``exec`` tool. So instead
of inspecting ``exec`` command strings, they parse ``posthog-cli`` invocations
out of the agent's ``Bash`` tool calls.

Each case carries its per-scorer params under the scorer's ``_name()`` in
``expected`` (same convention as ``cli_mcp``):

    expected = {
        "called_cli_command": {"category": "feature-flag", "verb": "get-all"},
    }

Scorers default to ``score=None`` when their key is missing, so unrelated cases
don't drag the rollup down.

The command-parsing core (:func:`parse_cli_invocations`, :func:`cli_invocations`)
is pure and unit-tested in ``test_scorers.py`` without the sandbox.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import LogParser, ToolCall

BASH_TOOL_NAME = "Bash"
CLI_BIN = "posthog-cli"
# Split a (possibly compound) shell command into segments so a `posthog-cli ... | jq`
# or `a && posthog-cli ...` still surfaces the posthog-cli call.
_SEGMENT_SPLIT = re.compile(r"\|\||&&|\||;|\n")

__all__ = [
    "CalledCliCommand",
    "DryRanBeforeWrite",
    "UsedHelpDiscovery",
    "parse_cli_invocations",
]


@dataclass(frozen=True)
class CliInvocation:
    """A single ``posthog-cli`` invocation parsed from a shell command."""

    category: str | None
    verb: str | None
    is_help: bool
    is_dry_run: bool
    raw: str


def _looks_like_cli(token: str) -> bool:
    return token == CLI_BIN or token.endswith("/" + CLI_BIN)


def parse_cli_invocations(command: str) -> list[CliInvocation]:
    """Extract every ``posthog-cli`` invocation from a shell command string.

    Handles compound commands (pipes, ``&&``) and quoted ``--json`` payloads.
    Category and verb are the first two positional tokens before any flag — which
    is exactly the clap structure (``posthog-cli <category> <verb> [flags]``), so a
    flag value like ``--key x`` is never mistaken for a positional.
    """
    invocations: list[CliInvocation] = []
    for segment in _SEGMENT_SPLIT.split(command):
        if CLI_BIN not in segment:
            continue
        try:
            tokens = shlex.split(segment)
        except ValueError:
            continue
        for i, token in enumerate(tokens):
            if not _looks_like_cli(token):
                continue
            rest = tokens[i + 1 :]
            is_help = any(t in ("--help", "-h") for t in rest)
            is_dry_run = "--dry-run" in rest
            positionals: list[str] = []
            for t in rest:
                if t.startswith("-"):
                    break
                positionals.append(t)
            invocations.append(
                CliInvocation(
                    category=positionals[0] if positionals else None,
                    verb=positionals[1] if len(positionals) > 1 else None,
                    is_help=is_help,
                    is_dry_run=is_dry_run,
                    raw=segment.strip(),
                )
            )
    return invocations


def cli_invocations(calls: list[ToolCall]) -> list[tuple[CliInvocation, ToolCall]]:
    """Pair every parsed ``posthog-cli`` invocation with its originating Bash call."""
    paired: list[tuple[CliInvocation, ToolCall]] = []
    for call in calls:
        if call.name != BASH_TOOL_NAME:
            continue
        command = call.input.get("command")
        if not isinstance(command, str):
            continue
        for inv in parse_cli_invocations(command):
            paired.append((inv, call))
    return paired


# ---- Pure scoring logic (unit-tested directly) ----


def score_called_command(calls: list[ToolCall], category: str, verb: str) -> tuple[float, dict]:
    matched = [
        (inv, c)
        for inv, c in cli_invocations(calls)
        if inv.category == category and inv.verb == verb and not inv.is_dry_run
    ]
    succeeded = [c for _, c in matched if not c.is_error]
    if succeeded:
        return 1.0, {"category": category, "verb": verb, "call_id": succeeded[0].call_id}
    if matched:
        return 0.0, {"reason": f"`{category} {verb}` ran but errored"}
    return 0.0, {"reason": f"`{category} {verb}` was never invoked"}


def score_used_help_discovery(calls: list[ToolCall]) -> tuple[float | None, dict]:
    invs = cli_invocations(calls)
    if not invs:
        return None, {"reason": "no posthog-cli usage"}
    helps = [c for inv, c in invs if inv.is_help]
    commands = [c for inv, c in invs if not inv.is_help and inv.category]
    if not helps:
        return 0.0, {"reason": "no --help discovery before running a command"}
    if not commands:
        return 1.0, {"reason": "used --help"}
    first_help = min(c.position for c in helps)
    first_command = min(c.position for c in commands)
    return (1.0 if first_help <= first_command else 0.0), {"first_help": first_help, "first_command": first_command}


def score_dry_ran_before_write(calls: list[ToolCall], category: str, verb: str) -> tuple[float | None, dict]:
    matched = [(inv, c) for inv, c in cli_invocations(calls) if inv.category == category and inv.verb == verb]
    if not matched:
        return None, {"reason": f"`{category} {verb}` never invoked"}
    dry_positions = [c.position for inv, c in matched if inv.is_dry_run]
    real_positions = [c.position for inv, c in matched if not inv.is_dry_run]
    if not real_positions:
        return 1.0, {"reason": "only previewed with --dry-run (never wrote)"}
    if not dry_positions:
        return 0.0, {"reason": "wrote without a preceding --dry-run"}
    return (1.0 if min(dry_positions) < min(real_positions) else 0.0), {
        "first_dry_run": min(dry_positions),
        "first_write": min(real_positions),
    }


# ---- Scorer wiring ----


def _read_spec(expected: dict | None, scorer_name: str) -> dict | None:
    if not isinstance(expected, dict):
        return None
    spec = expected.get(scorer_name)
    return spec if isinstance(spec, dict) else None


def _bash_calls(output: dict | None) -> list[ToolCall] | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not raw_log:
        return None
    return LogParser(raw_log, initial_prompt=output.get("prompt", "") or "").get_tool_calls(BASH_TOOL_NAME)


class _CliScorer(Scorer):
    """Shared async/sync plumbing; subclasses implement ``_name`` + ``_evaluate``."""

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:  # pragma: no cover - overridden
        raise NotImplementedError


class CalledCliCommand(_CliScorer):
    """Binary: did the agent successfully run ``posthog-cli <category> <verb>``?"""

    def _name(self) -> str:
        return "called_cli_command"

    def _evaluate(self, output, expected) -> Score:
        spec = _read_spec(expected, self._name())
        if not spec or "category" not in spec or "verb" not in spec:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        calls = _bash_calls(output)
        if calls is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        score, metadata = score_called_command(calls, spec["category"], spec["verb"])
        return Score(name=self._name(), score=score, metadata=metadata)


class UsedHelpDiscovery(_CliScorer):
    """Binary: did the agent use ``--help`` to discover a command before running one?"""

    def _name(self) -> str:
        return "used_help_discovery"

    def _evaluate(self, output, expected) -> Score:
        if _read_spec(expected, self._name()) is None:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        calls = _bash_calls(output)
        if calls is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        score, metadata = score_used_help_discovery(calls)
        return Score(name=self._name(), score=score, metadata=metadata)


class DryRanBeforeWrite(_CliScorer):
    """Binary: before a write, did the agent preview it with ``--dry-run``?"""

    def _name(self) -> str:
        return "dry_ran_before_write"

    def _evaluate(self, output, expected) -> Score:
        spec = _read_spec(expected, self._name())
        if not spec or "category" not in spec or "verb" not in spec:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        calls = _bash_calls(output)
        if calls is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        score, metadata = score_dry_ran_before_write(calls, spec["category"], spec["verb"])
        return Score(name=self._name(), score=score, metadata=metadata)
