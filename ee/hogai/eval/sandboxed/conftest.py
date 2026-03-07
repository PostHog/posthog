from __future__ import annotations

from collections.abc import Generator

import pytest

from posthog.models import Organization, Team, User

# We want the PostHog set_up_evals fixture here
from ee.hogai.eval.conftest import set_up_evals  # noqa: F401
from ee.hogai.eval.data_setup import create_core_memory, create_demo_org_team_user
from ee.models.assistant import CoreMemory

from .config import SandboxEvalConfig
from .runner import SandboxedEvalRunner


@pytest.fixture(scope="session", autouse=True)
def demo_org_team_user(
    set_up_evals,  # noqa: F811
    django_db_blocker,
) -> Generator[tuple[Organization, Team, User], None, None]:
    yield create_demo_org_team_user(django_db_blocker)


@pytest.fixture(scope="session", autouse=True)
def core_memory(demo_org_team_user, django_db_blocker) -> Generator[CoreMemory, None, None]:
    yield create_core_memory(demo_org_team_user[1], django_db_blocker)


@pytest.fixture(scope="session")
def sandbox_eval_config() -> SandboxEvalConfig:
    """Default sandbox eval configuration. Override in tests if needed."""
    return SandboxEvalConfig()


@pytest.fixture(scope="session")
def sandbox_runner(sandbox_eval_config: SandboxEvalConfig) -> SandboxedEvalRunner:
    """Session-scoped eval runner instance."""
    return SandboxedEvalRunner(config=sandbox_eval_config)
