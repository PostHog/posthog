"""Eval cases for the real ``posthog-cli`` binary, driven by a coding agent via Bash.

Where ``cli_mcp`` exercises the MCP server's ``exec`` (CLI-*like*) tool, this suite
exercises the actual ``posthog-cli`` binary: the agent discovers and runs commands
through ``Bash`` (``posthog-cli <category> <verb> [--flags] [--json ...]``).

PREREQUISITE (not yet wired): the sandbox image must ship the ``posthog-cli`` binary
on PATH, authenticated against the per-case demo project (``POSTHOG_CLI_API_KEY`` /
``POSTHOG_CLI_PROJECT_ID`` / ``POSTHOG_CLI_HOST``), with the steering block installed
(``posthog-cli init``). Until that is in place these cases will run but the agent has
no binary to call, so they will score 0. The harness, cases, and scorers are complete;
only the sandbox provisioning is outstanding.

To run a single eval (once the sandbox ships the binary):
    pytest ee/hogai/eval/sandboxed/cli_posthog/eval_workflow.py::eval_help_discovery
"""

from __future__ import annotations

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.cli_posthog.scorers import CalledCliCommand, DryRanBeforeWrite, UsedHelpDiscovery
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero


async def eval_help_discovery(sandboxed_demo_data, pytestconfig, posthog_client):
    """Open-ended read — the agent should discover the command via ``--help`` and run it."""
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="list_feature_flags",
            prompt="Using the PostHog CLI, list all feature flags in this project.",
            expected={
                "called_cli_command": {"category": "feature-flag", "verb": "get-all"},
                "used_help_discovery": {},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-posthog-help-discovery",
        cases=cases,
        scorers=[ExitCodeZero(), CalledCliCommand(), UsedHelpDiscovery()],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )


async def eval_dry_run_before_write(sandboxed_demo_data, pytestconfig, posthog_client):
    """Write scenario — the agent should preview with ``--dry-run`` before creating."""
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="create_feature_flag",
            prompt=(
                "Using the PostHog CLI, create a feature flag with key `eval-cli-test` "
                "named 'Eval CLI Test'. Preview the request before you run it for real."
            ),
            expected={
                "called_cli_command": {"category": "feature-flag", "verb": "create"},
                "dry_ran_before_write": {"category": "feature-flag", "verb": "create"},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-posthog-dry-run-before-write",
        cases=cases,
        scorers=[ExitCodeZero(), CalledCliCommand(), DryRanBeforeWrite()],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
