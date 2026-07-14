from __future__ import annotations

import os
import argparse
from dataclasses import dataclass
from typing import get_args

from .providers import DockerProviderStrategy, ModalProviderStrategy, SandboxProvider

# Bare model ids, no "anthropic/"/"openai/" prefix: the LLM gateway checks the model
# against a bare-id allowlist with startswith, so the prefixed form is rejected with a
# 403 and the agent finishes without doing anything — while still scoring exit_code_zero=1.
DEFAULT_AGENT_MODEL = "claude-opus-4-8"
DEFAULT_CODEX_AGENT_MODEL = "gpt-5.5"

# Literal mirror of products.tasks' RuntimeAdapter values: this module must stay
# Django-free (see harness/AGENTS.md), so it cannot import the enum.
AGENT_RUNTIMES = ("claude", "codex")
DEFAULT_AGENT_MODEL_BY_RUNTIME = {"claude": DEFAULT_AGENT_MODEL, "codex": DEFAULT_CODEX_AGENT_MODEL}
DEFAULT_CASE_TIMEOUT_SECONDS = 60 * 15
OFFLINE_CASE_TIMEOUT_SECONDS = 60 * 60

TEAM_SETUP_CONCURRENCY = 1
"""Per-case team setups allowed at once. Setup copies ClickHouse data and some
case seeders write there directly, so overlapping setups can exhaust local RAM."""

UNBOUNDED_SANDBOXES = 1 << 20
"""Semaphore value standing in for "no limit" — larger than any case count."""


@dataclass(frozen=True)
class HarnessOptions:
    selectors: tuple[str, ...]
    provider: SandboxProvider
    case_filter: str | None
    agent_model: str
    agent_runtime: str
    reasoning_effort: str | None
    max_sandboxes: int
    keep_sandbox_containers: bool
    rebuild_sandbox_image: bool
    create_db: bool
    list_only: bool
    per_case_timeout_seconds: int
    trials: int
    fail_under: float | None


def _default_case_timeout() -> int:
    if os.getenv("EVAL_MODE") == "offline":
        return OFFLINE_CASE_TIMEOUT_SECONDS
    return DEFAULT_CASE_TIMEOUT_SECONDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ee.hogai.eval.sandboxed.harness",
        description=(
            "Run the sandboxed agent evals. Boots the shared session infrastructure once, "
            "then runs every selected suite concurrently under a single global sandbox limit."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "selectors",
        nargs="*",
        help="Substring selectors matched against '<domain>/<module>::<fn>'. Omit to run everything.",
    )
    parser.add_argument(
        "--provider",
        choices=get_args(SandboxProvider),
        default="docker",
        help="Where sandboxes run. 'modal' starts ngrok tunnels so remote sandboxes can reach this host.",
    )
    parser.add_argument("--eval", dest="case_filter", default=None, help="Only run cases whose name contains this.")
    parser.add_argument(
        "--agent-model",
        default=None,
        help=(
            f"Model the sandboxed agent runs against "
            f"(default: {DEFAULT_AGENT_MODEL} for claude, {DEFAULT_CODEX_AGENT_MODEL} for codex)."
        ),
    )
    parser.add_argument(
        "--agent-runtime",
        choices=AGENT_RUNTIMES,
        default="claude",
        help="Agent runtime serving the model. 'codex' additionally requires LLM_GATEWAY_OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help="Agent reasoning effort (e.g. 'low'…'xhigh'); valid values depend on runtime+model.",
    )
    parser.add_argument(
        "--max-sandboxes",
        type=int,
        default=None,
        help=(
            f"Concurrently live sandboxes across all suites "
            f"(default: {DockerProviderStrategy.default_max_sandboxes} for docker, unbounded for modal)."
        ),
    )
    parser.add_argument(
        "--keep-sandbox-containers",
        action="store_true",
        help="Skip the end-of-run Docker container sweep, for debugging a leftover container.",
    )
    parser.add_argument(
        "--rebuild-sandbox-image",
        action="store_true",
        help="Force a rebuild of the posthog-sandbox-base image before the run (docker only).",
    )
    parser.add_argument(
        "--create-db", action="store_true", help="Rebuild the eval test database instead of reusing it."
    )
    parser.add_argument(
        "--list", dest="list_only", action="store_true", help="Print the discovered suite ids and exit."
    )
    parser.add_argument(
        "--case-timeout",
        type=int,
        default=None,
        help=f"Agent-run budget in seconds, started after team setup (default: {_default_case_timeout()}).",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="Run every case this many times (Braintrust trials), to measure variance on stochastic agents.",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="Exit nonzero when the mean score across all experiments falls below this fraction (0-1).",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> HarnessOptions:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.max_sandboxes is not None and args.max_sandboxes < 1:
        parser.error("--max-sandboxes must be at least 1")
    if args.keep_sandbox_containers and args.provider != "docker":
        parser.error("--keep-sandbox-containers only applies to --provider docker")
    if args.rebuild_sandbox_image and args.provider != "docker":
        parser.error("--rebuild-sandbox-image only applies to --provider docker")
    if args.trials < 1:
        parser.error("--trials must be at least 1")

    # A runtime/model mismatch otherwise surfaces minutes into the run as an opaque
    # gateway 403, with the agent finishing without doing anything.
    agent_model = args.agent_model or DEFAULT_AGENT_MODEL_BY_RUNTIME[args.agent_runtime]
    if args.agent_runtime == "codex" and agent_model.startswith("claude"):
        parser.error(f"--agent-model {agent_model} is a Claude model; the codex runtime serves gpt-* models")
    if args.agent_runtime == "claude" and agent_model.startswith("gpt"):
        parser.error(f"--agent-model {agent_model} is an OpenAI model; pass --agent-runtime codex to serve it")
    if args.fail_under is not None and not (0 < args.fail_under <= 1):
        parser.error("--fail-under must be greater than 0 and at most 1")

    default_slots = (
        DockerProviderStrategy.default_max_sandboxes
        if args.provider == "docker"
        else ModalProviderStrategy.default_max_sandboxes
    )
    max_sandboxes = args.max_sandboxes or default_slots or UNBOUNDED_SANDBOXES

    return HarnessOptions(
        selectors=tuple(args.selectors),
        provider=args.provider,
        case_filter=args.case_filter,
        agent_model=agent_model,
        agent_runtime=args.agent_runtime,
        reasoning_effort=args.reasoning_effort,
        max_sandboxes=max_sandboxes,
        keep_sandbox_containers=args.keep_sandbox_containers,
        rebuild_sandbox_image=args.rebuild_sandbox_image,
        create_db=args.create_db,
        list_only=args.list_only,
        per_case_timeout_seconds=args.case_timeout or _default_case_timeout(),
        trials=args.trials,
        fail_under=args.fail_under,
    )
