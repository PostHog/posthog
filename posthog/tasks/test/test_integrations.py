import time
from datetime import timedelta
from typing import Optional

import pytest
import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.models import Team
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration
from posthog.redis import get_client as get_redis_client
from posthog.tasks.integrations import (
    refresh_github_branch_cache,
    refresh_integration,
    refresh_integrations,
    revalidate_github_installation,
)


class TestIntegrationsTasks(APIBaseTest):
    integrations: list[Integration] = []

    def setUp(self) -> None:
        super().setUp()

    def create_integration(
        self, kind: str, config: Optional[dict] = None, sensitive_config: Optional[dict] = None
    ) -> Integration:
        _config = {"refreshed_at": int(time.time()), "expires_in": 3600}
        _sensitive_config = {"refresh_token": "REFRESH"}
        _config.update(config or {})
        _sensitive_config.update(sensitive_config or {})

        return Integration.objects.create(team=self.team, kind=kind, config=_config, sensitive_config=_sensitive_config)

    def test_refresh_integrations_schedules_refreshes_for_expired(self) -> None:
        _integration_1 = self.create_integration("other")  # not an oauth one
        _integration_2 = self.create_integration("slack")  # not expired
        integration_3 = self.create_integration("slack", config={"refreshed_at": time.time() - 3600})  # expired
        integration_4 = self.create_integration(
            "slack", config={"refreshed_at": time.time() - 3600 + 170}
        )  # expired with buffer

        with patch("posthog.tasks.integrations.refresh_integration.delay") as refresh_integration_mock:
            refresh_integrations()
            # Both 3 and 4 should be refreshed
            assert refresh_integration_mock.call_args_list == [((integration_3.id,),), ((integration_4.id,),)]

    def test_refresh_integrations_excludes_resend(self) -> None:
        # Resend's refresh token is single-use and rotates on every refresh; the periodic sweep is
        # unlocked and would race the row-locked sync-path refresh, double-spending the token and
        # revoking the grant. An expired Resend row must never be enqueued here.
        self.create_integration("resend", config={"refreshed_at": time.time() - 3600})
        eligible = self.create_integration("slack", config={"refreshed_at": time.time() - 3600})

        with patch("posthog.tasks.integrations.refresh_integration.delay") as refresh_integration_mock:
            refresh_integrations()

        assert refresh_integration_mock.call_args_list == [((eligible.id,),)]

    def test_refresh_integration_skips_resend(self) -> None:
        # Defense in depth for a task enqueued before the sweep exclusion shipped: even if a Resend
        # id reaches refresh_integration, it must not spend the rotating token via the unlocked path.
        integration = self.create_integration("resend", config={"refreshed_at": time.time() - 3600})

        with patch("posthog.models.integration.oauth.OauthIntegration.refresh_access_token") as refresh_mock:
            refresh_integration(integration.id)

        assert refresh_mock.called is False

    def test_refresh_integrations_skips_backed_off_and_terminal(self) -> None:
        expired = {"refreshed_at": time.time() - 3600}
        eligible = self.create_integration("slack", config=expired)
        backoff_elapsed = self.create_integration(
            "slack",
            config={**expired, "refresh_failure_count": 2, "refresh_next_attempt_at": int(time.time()) - 10},
        )
        _backed_off = self.create_integration(
            "slack",
            config={**expired, "refresh_failure_count": 2, "refresh_next_attempt_at": int(time.time()) + 300},
        )
        _terminal = self.create_integration(
            "slack", config={**expired, "refresh_failure_count": 5, "refresh_terminal": True}
        )

        with patch("posthog.tasks.integrations.refresh_integration.delay") as refresh_integration_mock:
            refresh_integrations()

        assert refresh_integration_mock.call_args_list == [((eligible.id,),), ((backoff_elapsed.id,),)]

    def test_refresh_integration_skips_when_backed_off(self) -> None:
        integration = self.create_integration(
            "slack",
            config={
                "refreshed_at": time.time() - 3600,
                "refresh_failure_count": 1,
                "refresh_next_attempt_at": int(time.time()) + 300,
            },
        )

        with patch("posthog.models.integration.oauth.OauthIntegration.refresh_access_token") as refresh_mock:
            refresh_integration(integration.id)

        assert refresh_mock.called is False

    @parameterized.expand(
        [
            ("expired", int(time.time()) - 3600, True),
            ("fresh", int(time.time()), False),
        ]
    )
    def test_refresh_integration_mints_only_when_still_expired(
        self, _name: str, refreshed_at: float, expected_refreshed: bool
    ) -> None:
        # Duplicate tasks can queue up for one row under backlog; refresh_integration must re-check the
        # just-loaded row so a task that finds it already fresh skips the mint instead of re-minting.
        integration = self.create_integration("github", config={"refreshed_at": refreshed_at, "expires_in": 3600})

        with patch("posthog.models.integration.github.GitHubIntegration.refresh_access_token") as refresh_mock:
            refresh_integration(integration.id)

        assert refresh_mock.called is expected_refreshed

    @parameterized.expand(
        [
            ("budget_shed_keeps_lock_for_the_retry", GitHubEgressBudgetExhausted("shed", scope="1"), True),
            ("other_error_releases_lock", RuntimeError("boom"), False),
        ]
    )
    def test_branch_refresh_holds_its_lock_only_while_a_retry_is_pending(
        self, _name: str, error: Exception, lock_held: bool
    ) -> None:
        integration = self.create_integration("github", config={"installation_id": "INSTALL"})
        github = GitHubIntegration(integration, source="test", priority=Priority.BATCH)
        lock_key = github._branch_refresh_lock_key("posthog/posthog")
        get_redis_client().set(lock_key, "token")
        self.addCleanup(get_redis_client().delete, lock_key)

        with (
            patch("posthog.models.integration.github.GitHubIntegration.refresh_branch_cache", side_effect=error),
            pytest.raises(type(error)),
        ):
            refresh_github_branch_cache(str(integration.id), "posthog/posthog", False, "token")

        assert (get_redis_client().get(lock_key) == b"token") is lock_held

    def test_branch_refresh_leaves_a_newer_refresh_lock_alone(self) -> None:
        integration = self.create_integration("github", config={"installation_id": "INSTALL"})
        github = GitHubIntegration(integration, source="test", priority=Priority.BATCH)
        lock_key = github._branch_refresh_lock_key("posthog/posthog")
        get_redis_client().set(lock_key, "newer")
        self.addCleanup(get_redis_client().delete, lock_key)

        with patch("posthog.models.integration.github.GitHubIntegration.refresh_branch_cache"):
            refresh_github_branch_cache(str(integration.id), "posthog/posthog", False, "older")

        assert get_redis_client().get(lock_key) == b"newer"

    @parameterized.expand(
        [
            ("retry_after", False, 180, None, False, 180),
            ("reset_at", True, None, 240, False, 240),
            ("budget", False, None, None, True, 60),
            ("no_hint", True, None, None, False, 60),
        ]
    )
    @time_machine.travel("2026-01-15T12:00:00Z", tick=False)
    def test_installation_revalidation_survives_repeated_cooldowns(
        self, _name: str, personal: bool, retry_after: int | None, reset_in: int | None, budget: bool, countdown: int
    ) -> None:
        config = {"installation_id": "restored", "installation_unavailable_since": 1}
        github_type: type[GitHubIntegrationBase]
        if personal:
            integration: Integration | UserIntegration = UserIntegration.objects.create(
                user=self.user, kind="github", integration_id="restored", config=config
            )
            github_type = UserGitHubIntegration
        else:
            integration = Integration.objects.create(
                team=self.team, kind="github", integration_id="restored", config=config
            )
            github_type = GitHubIntegration
        now = int(time.time())
        error = (
            GitHubEgressBudgetExhausted("Budget exhausted", scope="restored")
            if budget
            else GitHubRateLimitError(
                "Rate limited", retry_after=retry_after, reset_at=now + reset_in if reset_in else None
            )
        )
        response = Mock(status_code=201)
        response.json.return_value = {
            "token": "fake-installation-token",
            "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
        }
        with (
            patch("posthog.tasks.integrations.time.time", return_value=now),
            patch.object(github_type, "client_request", side_effect=[error] * 7 + [response]),
            patch.object(github_type, "sync_repository_cache") as sync,
            patch.object(revalidate_github_installation, "apply_async") as schedule,
            patch.object(revalidate_github_installation, "delay") as next_phase,
        ):
            for attempt in range(7):
                revalidate_github_installation("restored", personal=personal)
                assert schedule.call_count == attempt + 1
                schedule.assert_called_with(
                    args=["restored"], kwargs={"personal": personal, "after_id": None}, countdown=countdown
                )
                integration.refresh_from_db()
                assert "installation_unavailable_since" in integration.config
                sync.assert_not_called()
                next_phase.assert_not_called()
            revalidate_github_installation("restored", personal=personal)
        integration.refresh_from_db()
        assert "installation_unavailable_since" not in integration.config
        sync.assert_called_once()
        assert schedule.call_count == 7
        if not personal:
            next_phase.assert_called_once_with("restored", personal=True)

    def test_installation_revalidation_resumes_after_completed_connections(self) -> None:
        completed = Integration.objects.create(team=self.team, kind="github", integration_id="shared")
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        Integration.objects.create(team=other_team, kind="github", integration_id="shared")
        with (
            patch.object(
                GitHubIntegration,
                "refresh_access_token",
                side_effect=[None, GitHubRateLimitError("Rate limited", retry_after=120)],
            ) as refresh,
            patch.object(GitHubIntegration, "sync_repository_cache") as sync,
            patch.object(revalidate_github_installation, "apply_async") as schedule,
            patch.object(revalidate_github_installation, "delay"),
        ):
            revalidate_github_installation("shared")
            assert refresh.call_count == 2
            sync.assert_called_once()
            schedule.assert_called_once_with(
                args=["shared"], kwargs={"personal": False, "after_id": str(completed.pk)}, countdown=120
            )
            refresh.side_effect = None
            refresh.reset_mock()
            revalidate_github_installation("shared", personal=False, after_id=str(completed.pk))
            refresh.assert_called_once()
