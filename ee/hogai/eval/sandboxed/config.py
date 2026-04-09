from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SandboxedExpected(BaseModel):
    """Expected outcomes for scoring a sandboxed agent eval case."""

    files_modified: list[str] | None = None
    """Paths (relative to repo root) that should be modified by the agent."""

    tests_should_pass: bool = True
    """Whether the test suite should pass after the agent runs."""

    lint_should_pass: bool = True
    """Whether the linter should pass after the agent runs."""

    pr_created: bool = False
    """Whether the agent should create a PR."""

    custom_assertions: dict[str, Any] = Field(default_factory=dict)
    """Scorer-specific expected values (e.g. expected file contents, patterns)."""


class SandboxedEvalCase(BaseModel):
    """A single eval case for the sandboxed coding agent."""

    name: str
    """Human-readable name for this eval case."""

    prompt: str
    """Natural language task description for the agent."""

    repo_fixture: str = ""
    """Name of the repo fixture (informational, for tracking)."""

    expected: SandboxedExpected = Field(default_factory=SandboxedExpected)
    """Expected outcomes for scoring."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Arbitrary metadata for tracking and filtering."""


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
