from __future__ import annotations

from collections.abc import Generator

import pytest

from django.conf import settings

from posthog.models import Organization, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.tasks.backend.temporal.process_task.utils import McpServerConfig

# We want the PostHog set_up_evals fixture here
from ee.hogai.eval.conftest import set_up_evals  # noqa: F401
from ee.hogai.eval.data_setup import create_core_memory, create_isolated_demo_data
from ee.models.assistant import CoreMemory

from .config import SandboxEvalConfig
from .runner import SandboxedEvalRunner


def _worker_label(worker_id: str) -> str:
    """Derive a unique label from the pytest-xdist worker id.

    ``worker_id`` is ``"gw0"``, ``"gw1"``, … under xdist, or ``"master"``
    when running without it.  Each label maps to its own isolated
    org/team/user so parallel workers never collide.
    """
    return f"sandboxed-{worker_id}"


@pytest.fixture(scope="session", autouse=True)
def demo_org_team_user(
    set_up_evals,  # noqa: F811
    django_db_blocker,
    worker_id,
) -> Generator[tuple[Organization, Team, User], None, None]:
    yield create_isolated_demo_data(django_db_blocker, label=_worker_label(worker_id))


@pytest.fixture(scope="session", autouse=True)
def core_memory(demo_org_team_user, django_db_blocker) -> Generator[CoreMemory, None, None]:
    yield create_core_memory(demo_org_team_user[1], django_db_blocker)


@pytest.fixture(scope="session")
def sandbox_eval_config(demo_org_team_user, django_db_blocker) -> SandboxEvalConfig:
    """Build sandbox config with env vars pointing to the local PostHog instance.

    Each xdist worker gets its own API key scoped to its own isolated team,
    so parallel eval runs never see each other's data or mutations.
    """
    _org, team, user = demo_org_team_user

    with django_db_blocker.unblock():
        api_key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=user,
            label=f"eval-sandbox-{team.pk}",
            secure_value=hash_key_value(api_key_value),
            scopes=["project:read"],
            scoped_teams=[team.id],
        )

    api_url = getattr(settings, "SANDBOX_API_URL", None) or settings.SITE_URL or "http://localhost:8000"

    return SandboxEvalConfig(
        environment_variables={
            "POSTHOG_API_URL": api_url,
            "POSTHOG_PERSONAL_API_KEY": api_key_value,
            "POSTHOG_PROJECT_ID": str(team.project_id),
        },
    )


def _build_mcp_configs(team: Team, api_key: str, mcp_url: str | None = None) -> list[McpServerConfig]:
    """Build MCP server config pointing to the local PostHog MCP server."""
    url = mcp_url or getattr(settings, "SANDBOX_MCP_URL", None) or "http://localhost:8787/mcp"
    return [
        McpServerConfig(
            type="http",
            name="posthog",
            url=url,
            headers=[
                {"name": "Authorization", "value": f"Bearer {api_key}"},
                {"name": "x-posthog-project-id", "value": str(team.project_id)},
                {"name": "x-posthog-mcp-version", "value": "2"},
                {"name": "x-posthog-read-only", "value": "true"},
            ],
        )
    ]


@pytest.fixture(scope="session")
def sandbox_runner(sandbox_eval_config: SandboxEvalConfig, demo_org_team_user) -> SandboxedEvalRunner:
    """Session-scoped eval runner instance with MCP config."""
    _org, team, _user = demo_org_team_user

    mcp_configs: list[McpServerConfig] | None = None
    if sandbox_eval_config.enable_mcp:
        api_key = sandbox_eval_config.environment_variables.get("POSTHOG_PERSONAL_API_KEY", "")
        mcp_configs = _build_mcp_configs(team, api_key, sandbox_eval_config.mcp_url)

    return SandboxedEvalRunner(config=sandbox_eval_config, mcp_configs=mcp_configs)
