from __future__ import annotations

import time
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from products.tasks.backend.services.sandbox import ExecutionResult, SandboxConfig

from .config import AgentArtifacts, SandboxedEvalCase, SandboxEvalConfig

if TYPE_CHECKING:
    from products.tasks.backend.services.docker_sandbox import DockerSandbox

logger = logging.getLogger(__name__)

SANDBOX_WORKSPACE = "/tmp/workspace"
SANDBOX_REPO_DIR = f"{SANDBOX_WORKSPACE}/eval-repo"


class SandboxedEvalRunner:
    """Orchestrates sandboxed agent evaluation runs.

    Lifecycle:
      1. ``setup_sandbox`` — creates a Docker sandbox and copies the repo fixture into it
      2. ``run_agent`` — executes ``runAgent.mjs`` inside the sandbox
      3. ``collect_artifacts`` — gathers git diff, test results, lint results
      4. ``cleanup`` — destroys the sandbox

    Callers should prefer the ``run_eval_case`` convenience method which wraps the full lifecycle.
    """

    def __init__(self, config: SandboxEvalConfig | None = None):
        self.config = config or SandboxEvalConfig()

    def _build_sandbox_config(self, case_name: str) -> SandboxConfig:
        env_vars = {**self.config.environment_variables}
        return SandboxConfig(
            name=f"eval-{case_name}",
            memory_gb=self.config.sandbox_memory_gb,
            cpu_cores=self.config.sandbox_cpu_cores,
            disk_size_gb=self.config.sandbox_disk_size_gb,
            default_execution_timeout_seconds=self.config.agent_timeout_seconds,
            environment_variables=env_vars or None,
        )

    def setup_sandbox(self, case: SandboxedEvalCase, repo_path: Path) -> DockerSandbox:
        """Create a sandbox and copy the repo fixture into it."""
        from products.tasks.backend.services.docker_sandbox import DockerSandbox

        sandbox_config = self._build_sandbox_config(case.name)
        sandbox = DockerSandbox.create(sandbox_config)

        # Copy repo files into the sandbox
        sandbox.execute(f"mkdir -p {SANDBOX_REPO_DIR}")
        _copy_directory_to_sandbox(sandbox, repo_path, SANDBOX_REPO_DIR)

        # Initialize git inside the sandbox repo if not already a git repo
        result = sandbox.execute(f"cd {SANDBOX_REPO_DIR} && git rev-parse --is-inside-work-tree 2>/dev/null")
        if result.exit_code != 0:
            sandbox.execute(f"cd {SANDBOX_REPO_DIR} && git init && git add -A && git commit -m 'initial commit'")

        logger.info(f"Sandbox {sandbox.id} ready with repo fixture '{case.repo_fixture}'")
        return sandbox

    def run_agent(self, sandbox: DockerSandbox, case: SandboxedEvalCase) -> ExecutionResult:
        """Run the agent inside the sandbox with the eval case prompt."""
        command = (
            f"cd /scripts && node runAgent.mjs"
            f" --repositoryPath {SANDBOX_REPO_DIR}"
            f" --prompt {_shell_quote(case.prompt)}"
            f" --max-turns {self.config.agent_max_turns}"
        )

        logger.info(f"Running agent in sandbox {sandbox.id} for case '{case.name}'")
        return sandbox.execute(command, timeout_seconds=self.config.agent_timeout_seconds)

    def collect_artifacts(
        self,
        sandbox: DockerSandbox,
        case: SandboxedEvalCase,
        agent_result: ExecutionResult,
        duration_seconds: float,
    ) -> AgentArtifacts:
        """Collect all artifacts from the sandbox after the agent run."""
        # Git diff
        diff_result = sandbox.execute(f"cd {SANDBOX_REPO_DIR} && git diff HEAD")
        git_diff = diff_result.stdout if diff_result.exit_code == 0 else ""

        # Changed files
        files_result = sandbox.execute(f"cd {SANDBOX_REPO_DIR} && git diff --name-only HEAD")
        files_changed = (
            [f.strip() for f in files_result.stdout.splitlines() if f.strip()] if files_result.exit_code == 0 else []
        )

        # Also include untracked files
        untracked_result = sandbox.execute(f"cd {SANDBOX_REPO_DIR} && git ls-files --others --exclude-standard")
        if untracked_result.exit_code == 0:
            untracked = [f.strip() for f in untracked_result.stdout.splitlines() if f.strip()]
            files_changed.extend(untracked)

        # Run tests if expected
        test_exit_code: int | None = None
        test_output = ""
        if case.expected.tests_should_pass is not None:
            test_result = sandbox.execute(
                f"cd {SANDBOX_REPO_DIR} && {case.test_command}",
                timeout_seconds=120,
            )
            test_exit_code = test_result.exit_code
            test_output = test_result.stdout + test_result.stderr

        # Run lint if expected
        lint_exit_code: int | None = None
        lint_output = ""
        if case.expected.lint_should_pass is not None:
            lint_result = sandbox.execute(
                f"cd {SANDBOX_REPO_DIR} && {case.lint_command}",
                timeout_seconds=60,
            )
            lint_exit_code = lint_result.exit_code
            lint_output = lint_result.stdout + lint_result.stderr

        return AgentArtifacts(
            exit_code=agent_result.exit_code,
            stdout=agent_result.stdout,
            stderr=agent_result.stderr,
            git_diff=git_diff,
            files_changed=files_changed,
            test_exit_code=test_exit_code,
            test_output=test_output,
            lint_exit_code=lint_exit_code,
            lint_output=lint_output,
            duration_seconds=duration_seconds,
        )

    def cleanup(self, sandbox: DockerSandbox) -> None:
        """Destroy the sandbox."""
        try:
            sandbox.destroy()
            logger.info(f"Destroyed sandbox {sandbox.id}")
        except Exception:
            logger.exception(f"Failed to destroy sandbox {sandbox.id}")

    def run_eval_case(
        self,
        case: SandboxedEvalCase,
        repo_path: Path,
    ) -> AgentArtifacts:
        """Run a full eval case lifecycle: setup → agent → collect → cleanup.

        This is the primary entry point for eval tasks.
        """
        sandbox = self.setup_sandbox(case, repo_path)
        try:
            start = time.monotonic()
            agent_result = self.run_agent(sandbox, case)
            duration = time.monotonic() - start

            artifacts = self.collect_artifacts(sandbox, case, agent_result, duration)
            return artifacts
        finally:
            if self.config.cleanup_on_success:
                self.cleanup(sandbox)


def _shell_quote(s: str) -> str:
    """Quote a string for safe use in a shell command."""
    import shlex

    return shlex.quote(s)


def _copy_directory_to_sandbox(sandbox: DockerSandbox, src: Path, dest: str) -> None:
    """Copy a local directory into the sandbox via tar."""
    import subprocess

    tar_proc = subprocess.run(
        ["tar", "-cf", "-", "-C", str(src), "."],
        capture_output=True,
    )
    if tar_proc.returncode != 0:
        raise RuntimeError(f"Failed to create tar archive: {tar_proc.stderr.decode()}")

    sandbox.write_file(f"{dest}/.repo.tar", tar_proc.stdout)
    sandbox.execute(f"cd {dest} && tar -xf .repo.tar && rm .repo.tar")
