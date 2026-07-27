from __future__ import annotations

import pytest

from products.conversations.backend.temporal.helpers import (
    CONVERSATIONS_SUPPORT_REPLY_ENV_NAME,
    get_or_create_support_sandbox_env,
)
from products.tasks.backend.models import SandboxEnvironment


@pytest.mark.django_db
class TestSupportSandboxEnv:
    def _make_team(self):
        from posthog.models.organization import Organization
        from posthog.models.team.team import Team

        org = Organization.objects.create(name="Test Org")
        return Team.objects.create(organization=org, name="Test Team")

    def test_egress_is_locked_down(self):
        # The support sandbox processes untrusted (public) ticket content with read MCP scopes,
        # so its egress must stay closed: CUSTOM with no allowlist means only the always-on
        # INFRASTRUCTURE_DOMAINS (posthog/anthropic/gateways) are reachable, not github/pypi/npm.
        team = self._make_team()

        env_id = get_or_create_support_sandbox_env(team.id)

        env = SandboxEnvironment.objects.get(id=env_id)
        assert env.network_access_level == SandboxEnvironment.NetworkAccessLevel.CUSTOM
        assert env.allowed_domains == []
        assert env.include_default_domains is False
        # No default trusted domains (github/pypi/npm/...) leak into the effective allowlist.
        assert env.get_effective_domains() == []

    def test_reasserts_lockdown_on_existing_env(self):
        # An env that predates the lockdown (or is tampered to TRUSTED) must be re-locked on the
        # next coordinator run, since dispatch reuses the same per-team env by name.
        team = self._make_team()
        SandboxEnvironment.objects.create(
            team_id=team.id,
            name=CONVERSATIONS_SUPPORT_REPLY_ENV_NAME,
            network_access_level=SandboxEnvironment.NetworkAccessLevel.TRUSTED,
        )

        env_id = get_or_create_support_sandbox_env(team.id)

        env = SandboxEnvironment.objects.get(id=env_id)
        assert env.network_access_level == SandboxEnvironment.NetworkAccessLevel.CUSTOM
        assert env.get_effective_domains() == []
