from __future__ import annotations

from dataclasses import dataclass, field
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
    """A single eval case for the sandboxed coding agent.

    Analogous to Braintrust's EvalCase but with sandbox-specific fields.
    """

    name: str
    """Human-readable name for this eval case."""

    prompt: str
    """Natural language task description for the agent."""

    repo_fixture: str
    """Name of the fixture function that builds the synthetic test repo."""

    expected: SandboxedExpected = Field(default_factory=SandboxedExpected)
    """Expected outcomes for scoring."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Arbitrary metadata for tracking and filtering."""

    test_command: str = "python -m pytest -x"
    """Command to run the test suite inside the sandbox."""

    lint_command: str = "ruff check ."
    """Command to run the linter inside the sandbox."""


class AgentArtifacts(BaseModel):
    """Collected outputs from a sandboxed agent run.

    Passed to scorers as the `output` value.
    """

    exit_code: int
    """Agent process exit code (0 = clean exit)."""

    stdout: str = ""
    """Agent stdout output."""

    stderr: str = ""
    """Agent stderr output."""

    git_diff: str = ""
    """Output of `git diff` after agent run (staged + unstaged changes)."""

    files_changed: list[str] = Field(default_factory=list)
    """List of file paths modified by the agent."""

    test_exit_code: int | None = None
    """Exit code from running the test suite (None if not run)."""

    test_output: str = ""
    """Combined stdout/stderr from running tests."""

    lint_exit_code: int | None = None
    """Exit code from running the linter (None if not run)."""

    lint_output: str = ""
    """Combined stdout/stderr from running the linter."""

    duration_seconds: float = 0.0
    """Wall-clock time for the agent run in seconds."""

    pr_url: str | None = None
    """URL of the created PR, if any."""


@dataclass
class SandboxEvalConfig:
    """Configuration for a sandboxed eval run."""

    agent_max_turns: int = 50
    """Maximum agent turns before forced stop."""

    agent_timeout_seconds: int = 600
    """Hard timeout for the agent process (seconds)."""

    trials: int = 1
    """Number of independent trials per case (for pass@k metrics)."""

    cleanup_on_success: bool = True
    """Whether to destroy the sandbox after a successful eval."""

    sandbox_memory_gb: float = 16
    """Memory allocation for the sandbox container."""

    sandbox_cpu_cores: float = 4
    """CPU cores for the sandbox container."""

    sandbox_disk_size_gb: float = 64
    """Disk size for the sandbox container."""

    environment_variables: dict[str, str] = field(default_factory=dict)
    """Extra environment variables injected into the sandbox."""
