from __future__ import annotations

import pytest

from .config import SandboxEvalConfig
from .runner import SandboxedEvalRunner


@pytest.fixture(scope="session")
def sandbox_eval_config() -> SandboxEvalConfig:
    """Default sandbox eval configuration. Override in tests if needed."""
    return SandboxEvalConfig()


@pytest.fixture(scope="session")
def sandbox_runner(sandbox_eval_config: SandboxEvalConfig) -> SandboxedEvalRunner:
    """Session-scoped eval runner instance."""
    return SandboxedEvalRunner(config=sandbox_eval_config)
