from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from posthoganalytics import Posthog

from .demo_data import SandboxedDemoData
from .providers import SandboxProvider, SandboxProviderStrategy
from .reporting import ProgressReporter


@dataclass
class EvalContext:
    """Everything a suite function needs, assembled once per harness run.

    Replaces the pytest fixtures (``sandboxed_demo_data``, ``pytestconfig``,
    ``posthog_client``) that suites used to take individually. Passed unchanged
    down into ``SandboxedEval``.
    """

    provider: SandboxProvider
    """Provider label, kept for display and metadata only."""

    provider_strategy: SandboxProviderStrategy
    """The live provider strategy — the behavior hook for per-case teardown."""

    agent_model: str
    """Model every sandboxed agent runs against. Pinned for stable comparisons."""

    agent_runtime: str
    """Runtime adapter serving the model (``"claude"`` | ``"codex"``)."""

    reasoning_effort: str | None
    """Agent reasoning effort override; ``None`` keeps the agent server's default."""

    case_filter: str | None
    """Substring filter on case names, from ``--eval``."""

    demo_data: SandboxedDemoData
    """Master Hedgebox seed plus the per-case isolated team factory."""

    posthog_client: Posthog | None
    """Analytics client for eval trace + evaluation event capture."""

    sandbox_slots: asyncio.Semaphore
    """The one global limiter on concurrently live sandboxes, shared by every suite."""

    team_setup_slots: asyncio.Semaphore
    """Serializes team cloning and case seeders to protect local ClickHouse RAM."""

    reporter: ProgressReporter
    """Owns all terminal output and the ``eval_results.jsonl`` export."""

    per_case_timeout_seconds: int
    """Budget for the agent run, started after team setup so queueing cannot consume it."""

    trials: int
    """Times each case runs. Agents are stochastic, so N runs per case measure
    the variance a single run can't reveal."""

    log_dirs: set[Path] = field(default_factory=set)
    """Local raw-agent-log directories, one per suite, surfaced in the final summary."""
