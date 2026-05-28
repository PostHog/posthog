"""Unit tests for the cli_posthog scorer logic.

These exercise the pure command-parsing + scoring functions directly against
hand-built ``ToolCall`` lists — no sandbox, Temporal, Braintrust run, or Django
DB required. Run with: ``pytest ee/hogai/eval/sandboxed/cli_posthog/test_scorers.py``
"""

from __future__ import annotations

from ee.hogai.eval.sandboxed.cli_posthog.scorers import (
    parse_cli_invocations,
    score_called_command,
    score_dry_ran_before_write,
    score_used_help_discovery,
)
from ee.hogai.eval.sandboxed.log_parser import ToolCall


def _bash(command: str, position: int, is_error: bool = False) -> ToolCall:
    return ToolCall(
        name="Bash",
        input={"command": command},
        output="",
        is_error=is_error,
        call_id=f"call-{position}",
        position=position,
        raw_name="Bash",
        is_exec_unwrapped=False,
    )


# ---- parse_cli_invocations ----


def test_parse_simple_command():
    [inv] = parse_cli_invocations("posthog-cli feature-flag get-all")
    assert (inv.category, inv.verb, inv.is_help, inv.is_dry_run) == ("feature-flag", "get-all", False, False)


def test_flag_values_are_not_positionals():
    [inv] = parse_cli_invocations("posthog-cli feature-flag create --key x --name 'My Flag'")
    assert (inv.category, inv.verb) == ("feature-flag", "create")


def test_help_levels():
    assert parse_cli_invocations("posthog-cli --help")[0].category is None
    mid = parse_cli_invocations("posthog-cli feature-flag --help")[0]
    assert (mid.category, mid.verb, mid.is_help) == ("feature-flag", None, True)


def test_dry_run_flag_detected():
    [inv] = parse_cli_invocations("posthog-cli feature-flag create --dry-run --key x")
    assert inv.is_dry_run and inv.category == "feature-flag" and inv.verb == "create"


def test_piped_command_is_found():
    [inv] = parse_cli_invocations("posthog-cli feature-flag get-all --json '{\"limit\":\"5\"}' | jq '.results'")
    assert (inv.category, inv.verb) == ("feature-flag", "get-all")


def test_non_cli_command_ignored():
    assert parse_cli_invocations("jq '.results' < out.json") == []


# ---- score_called_command ----


def test_called_command_success():
    calls = [_bash("posthog-cli feature-flag get-all", 0)]
    score, _ = score_called_command(calls, "feature-flag", "get-all")
    assert score == 1.0


def test_called_command_errored_is_zero():
    calls = [_bash("posthog-cli feature-flag get-all", 0, is_error=True)]
    score, meta = score_called_command(calls, "feature-flag", "get-all")
    assert score == 0.0 and "errored" in meta["reason"]


def test_called_command_never_invoked_is_zero():
    calls = [_bash("posthog-cli dashboard get-all", 0)]
    score, _ = score_called_command(calls, "feature-flag", "get-all")
    assert score == 0.0


def test_called_command_ignores_dry_run_only():
    calls = [_bash("posthog-cli feature-flag create --dry-run --key x", 0)]
    score, _ = score_called_command(calls, "feature-flag", "create")
    assert score == 0.0  # a dry-run is not a real invocation


# ---- score_used_help_discovery ----


def test_help_before_command_passes():
    calls = [
        _bash("posthog-cli feature-flag --help", 0),
        _bash("posthog-cli feature-flag get-all", 1),
    ]
    score, _ = score_used_help_discovery(calls)
    assert score == 1.0


def test_command_without_help_fails():
    calls = [_bash("posthog-cli feature-flag get-all", 0)]
    score, _ = score_used_help_discovery(calls)
    assert score == 0.0


def test_help_after_command_fails():
    calls = [
        _bash("posthog-cli feature-flag get-all", 0),
        _bash("posthog-cli feature-flag --help", 1),
    ]
    score, _ = score_used_help_discovery(calls)
    assert score == 0.0


def test_no_cli_usage_is_none():
    score, _ = score_used_help_discovery([_bash("ls -la", 0)])
    assert score is None


# ---- score_dry_ran_before_write ----


def test_dry_run_before_write_passes():
    calls = [
        _bash("posthog-cli feature-flag create --dry-run --key x", 0),
        _bash("posthog-cli feature-flag create --key x", 1),
    ]
    score, _ = score_dry_ran_before_write(calls, "feature-flag", "create")
    assert score == 1.0


def test_write_without_dry_run_fails():
    calls = [_bash("posthog-cli feature-flag create --key x", 0)]
    score, _ = score_dry_ran_before_write(calls, "feature-flag", "create")
    assert score == 0.0


def test_only_dry_run_passes():
    calls = [_bash("posthog-cli feature-flag create --dry-run --key x", 0)]
    score, _ = score_dry_ran_before_write(calls, "feature-flag", "create")
    assert score == 1.0


def test_dry_run_command_never_invoked_is_none():
    calls = [_bash("posthog-cli feature-flag get-all", 0)]
    score, _ = score_dry_ran_before_write(calls, "feature-flag", "create")
    assert score is None
