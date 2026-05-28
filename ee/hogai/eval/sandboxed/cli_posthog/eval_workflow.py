"""Eval cases for the real ``posthog-cli`` binary, driven by a coding agent via Bash.

Where ``cli_mcp`` exercises the MCP server's ``exec`` (CLI-*like*) tool, this suite
exercises the actual ``posthog-cli`` binary: the agent discovers and runs commands
through ``Bash`` (``posthog-cli <category> <verb> [--flags] [--json ...]``).

Provisioning (wired, eval-gated): the ``_sandboxed_local_cli`` conftest fixture builds
the dev binary from the working tree and sets ``SANDBOX_LOCAL_CLI_HOST_PATH``; on that
signal ``DockerSandbox`` bind-mounts it onto PATH and ``provision_sandbox`` mints a
per-case personal API key, injecting ``POSTHOG_CLI_API_KEY`` / ``POSTHOG_CLI_PROJECT_ID``
/ ``POSTHOG_CLI_HOST``. All of this is inert in production (the env var is never set).
The agent is told to use the CLI by the prompt, so the steering block (``posthog-cli
init``) is not required for these cases.

To run a single eval:
    pytest ee/hogai/eval/sandboxed/cli_posthog/eval_workflow.py::eval_help_discovery
"""

from __future__ import annotations

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.cli_posthog.scorers import (
    CalledCliCommand,
    ComposedWithPostProcessing,
    DryRanBeforeWrite,
    UsedHelpDiscovery,
)
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


async def eval_reads_across_categories(sandboxed_demo_data, pytestconfig, posthog_client):
    """Breadth check — the agent picks the right command across different categories."""
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="list_dashboards",
            prompt="Using the PostHog CLI, list all dashboards in this project.",
            expected={"called_cli_command": {"category": "dashboard", "verb": "get-all"}},
        ),
        SandboxedEvalCase(
            name="list_experiments",
            prompt="Using the PostHog CLI, list the experiments in this project.",
            expected={"called_cli_command": {"category": "experiment", "verb": "list"}},
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-posthog-reads-across-categories",
        cases=cases,
        scorers=[ExitCodeZero(), CalledCliCommand()],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )


async def eval_query_wrapper(sandboxed_demo_data, pytestconfig, posthog_client):
    """Query wrapper — the agent runs a trends query through the CLI's query commands."""
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="trends_pageviews",
            prompt="Using the PostHog CLI, run a trends query for `$pageview` events over the last 7 days.",
            expected={"called_cli_command": {"category": "query-wrapper", "verb": "trends"}},
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-posthog-query-wrapper",
        cases=cases,
        scorers=[ExitCodeZero(), CalledCliCommand()],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )


async def eval_composition(sandboxed_demo_data, pytestconfig, posthog_client):
    """Composition — the CLI's reason to exist: pull data, then post-process with jq/python."""
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="dashboards_count_long_names",
            prompt=(
                "Using the PostHog CLI, list every dashboard in this project, then count how many "
                "dashboard names have more than 3 whitespace-separated words. Pipe the CLI output "
                "through jq or a small Python script to compute the count — don't eyeball it. "
                "Return the count and those dashboard names."
            ),
            expected={
                "called_cli_command": {"category": "dashboard", "verb": "get-all"},
                "composed_with_post_processing": {},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-posthog-composition",
        cases=cases,
        scorers=[ExitCodeZero(), CalledCliCommand(), ComposedWithPostProcessing()],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
