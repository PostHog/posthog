from __future__ import annotations

import pytest

from products.conversations.backend.temporal.helpers import (
    CONVERSATIONS_SUPPORT_REPLY_ENV_NAME,
    get_or_create_support_sandbox_env,
    resolve_user_id_for_support,
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


@pytest.mark.django_db
class TestResolveUserIdForSupport:
    def _make_team_with_members(self):
        from posthog.models import User
        from posthog.models.organization import Organization
        from posthog.models.team.team import Team

        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        User.objects.create_and_join(org, "oldest@posthog.com", "password")
        newest = User.objects.create_and_join(org, "newest@posthog.com", "password")
        return team, newest

    def test_prefers_configured_run_as_user(self):
        team, newest = self._make_team_with_members()
        team.conversations_settings = {"ai_mcp_run_as_user_id": newest.id}
        team.save()

        assert resolve_user_id_for_support(team.id) == newest.id

    def test_falls_back_when_run_as_user_inactive(self):
        from posthog.models.organization import OrganizationMembership

        team, newest = self._make_team_with_members()
        team.conversations_settings = {"ai_mcp_run_as_user_id": newest.id}
        team.save()
        newest.is_active = False
        newest.save()

        membership = (
            OrganizationMembership.objects.filter(organization=team.organization, user__is_active=True)
            .order_by("id")
            .first()
        )
        assert membership is not None
        assert resolve_user_id_for_support(team.id) == membership.user_id

    def test_falls_back_when_run_as_user_not_in_org(self):
        from posthog.models import User
        from posthog.models.organization import Organization, OrganizationMembership

        team, _newest = self._make_team_with_members()
        outsider_org = Organization.objects.create(name="Other Org")
        outsider = User.objects.create_and_join(outsider_org, "outsider@posthog.com", "password")
        team.conversations_settings = {"ai_mcp_run_as_user_id": outsider.id}
        team.save()

        membership = (
            OrganizationMembership.objects.filter(organization=team.organization, user__is_active=True)
            .order_by("id")
            .first()
        )
        assert membership is not None
        assert resolve_user_id_for_support(team.id) == membership.user_id


@pytest.mark.django_db
class TestGetMcpInstallationIds:
    def test_unset_returns_empty_list(self):
        from posthog.models.organization import Organization
        from posthog.models.team.team import Team

        from products.conversations.backend.temporal.ai_reply.activities.draft import _get_mcp_installation_ids

        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")

        assert _get_mcp_installation_ids(team.id) == []

    def test_stored_ids_are_returned(self):
        from posthog.models.organization import Organization
        from posthog.models.team.team import Team

        from products.conversations.backend.temporal.ai_reply.activities.draft import _get_mcp_installation_ids

        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        installation_id = "11111111-1111-4111-8111-111111111111"
        team.conversations_settings = {"ai_mcp_installation_ids": [installation_id]}
        team.save()

        assert _get_mcp_installation_ids(team.id) == [installation_id]
