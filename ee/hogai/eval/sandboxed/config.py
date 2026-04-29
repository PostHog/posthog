from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext


class SandboxedEvalCase(BaseModel):
    """A single eval case for the sandboxed coding agent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    """Human-readable name for this eval case."""

    prompt: str
    """Natural language task description for the agent."""

    repo_fixture: str = ""
    """Name of the repo fixture (informational, for tracking)."""

    expected: dict[str, Any] = Field(default_factory=dict)
    """Expected values for scoring, keyed by scorer ``_name()``.

    Each scorer reads its own sub-entry — e.g. ``{"tests_pass": {"should_pass": True}}``.
    Missing keys mean the scorer falls back to its default behavior.
    """

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Arbitrary metadata for tracking and filtering."""

    setup: Callable[[CustomPromptSandboxContext], dict[str, Any]] | None = Field(
        default=None,
        exclude=True,
    )
    """Optional pre-run hook invoked once the per-case team/user has been
    provisioned, before the agent prompt is dispatched. Returns a dict that
    is merged into the task output under ``seed`` so scorers can read seeded
    entity IDs. Excluded from serialization — the callable never round-trips
    through Braintrust telemetry.
    """


class AgentArtifacts(BaseModel):
    """Collected outputs from a sandboxed agent run.

    Passed to scorers as the `output` value. Fields are populated by parsing
    the agent's JSONL session logs from S3.
    """

    exit_code: int
    """0 if the agent finished cleanly, 1 otherwise."""

    stdout: str = ""
    """Concatenated tool call output from the agent session."""

    stderr: str = ""
    """Error output, if any."""

    git_diff: str = ""
    """Git diff extracted from agent tool calls."""

    files_changed: list[str] = Field(default_factory=list)
    """File paths extracted from agent tool calls."""

    test_exit_code: int | None = None
    """Inferred exit code from test tool calls (None if not run)."""

    test_output: str = ""
    """Test output extracted from agent tool calls."""

    lint_exit_code: int | None = None
    """Inferred exit code from lint tool calls (None if not run)."""

    lint_output: str = ""
    """Lint output extracted from agent tool calls."""

    duration_seconds: float = 0.0
    """Wall-clock time for the agent run in seconds."""

    pr_url: str | None = None
    """URL of the created PR, if any."""
