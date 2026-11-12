import time
from datetime import timedelta
from typing import Optional

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db import OperationalError, connection
from django.utils import timezone

from parameterized import parameterized

from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.egress.limiter.policies import Priority
from posthog.integrations import CrossTeamFilter
from posthog.integrations.accessors import IntegrationReader
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.integration.email import lock_sender_domain
from posthog.models.team.team import Team
from posthog.redis import get_client as get_redis_client
from posthog.tasks.integrations import (
    delete_ses_identity_if_unused,
    expire_unverified_email_senders,
    refresh_github_branch_cache,
    refresh_integration,
    refresh_integrations,
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
            assert refresh_integration_mock.call_args_list == [
                ((integration_3.id, self.team.id),),
                ((integration_4.id, self.team.id),),
            ]

    def test_refresh_integrations_excludes_resend(self) -> None:
        # Resend's refresh token is single-use and rotates on every refresh; the periodic sweep is
        # unlocked and would race the row-locked sync-path refresh, double-spending the token and
        # revoking the grant. An expired Resend row must never be enqueued here.
        self.create_integration("resend", config={"refreshed_at": time.time() - 3600})
        eligible = self.create_integration("slack", config={"refreshed_at": time.time() - 3600})

        with patch("posthog.tasks.integrations.refresh_integration.delay") as refresh_integration_mock:
            refresh_integrations()

        assert refresh_integration_mock.call_args_list == [((eligible.id, self.team.id),)]

    def test_refresh_integration_skips_resend(self) -> None:
        # Defense in depth for a task enqueued before the sweep exclusion shipped: even if a Resend
        # id reaches refresh_integration, it must not spend the rotating token via the unlocked path.
        integration = self.create_integration("resend", config={"refreshed_at": time.time() - 3600})

        with patch("posthog.models.integration.oauth.OauthIntegration.refresh_access_token") as refresh_mock:
            refresh_integration(integration.id, self.team.id)

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

        assert refresh_integration_mock.call_args_list == [
            ((eligible.id, self.team.id),),
            ((backoff_elapsed.id, self.team.id),),
        ]

    def test_refresh_integration_without_team_does_nothing(self) -> None:
        # A task that a sweep enqueued before the team id existed cannot read a row.
        integration = self.create_integration("slack", config={"refreshed_at": time.time() - 3600})

        with patch("posthog.models.integration.oauth.OauthIntegration.refresh_access_token") as refresh_mock:
            refresh_integration(integration.id)

        assert refresh_mock.called is False

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
            refresh_integration(integration.id, self.team.id)

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
            refresh_integration(integration.id, self.team.id)

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
            refresh_github_branch_cache(str(integration.id), "posthog/posthog", False, "token", self.team.id)

        assert (get_redis_client().get(lock_key) == b"token") is lock_held

    @parameterized.expand(
        [
            ("queued_before_team_id_was_added", False),
            ("row_of_another_team", True),
        ]
    )
    def test_branch_refresh_skips_a_row_it_cannot_read_in_scope(self, _name: str, with_other_team: bool) -> None:
        integration = self.create_integration("github", config={"installation_id": "INSTALL"})
        other_team_id = self.team.id + 1000

        with patch("posthog.models.integration.github.GitHubIntegration.refresh_branch_cache") as mock_refresh:
            if with_other_team:
                refresh_github_branch_cache(str(integration.id), "posthog/posthog", False, "token", other_team_id)
            else:
                refresh_github_branch_cache(str(integration.id), "posthog/posthog", False, "token")

        mock_refresh.assert_not_called()

    @parameterized.expand(
        [
            ("domain_still_used", "example.com", False),
            ("domain_unused", None, True),
            ("only_other_domain_used", "other.example.com", True),
        ]
    )
    def test_delete_ses_identity_only_when_no_team_uses_the_domain(
        self, _name: str, row_domain: Optional[str], expect_delete: bool
    ) -> None:
        if row_domain:
            self.create_integration("email", config={"domain": row_domain})
        with patch("posthog.tasks.integrations.delete_ses_identity") as mock_delete:
            delete_ses_identity_if_unused("example.com")

        assert mock_delete.called is expect_delete

    @patch("posthog.tasks.integrations.delete_ses_identity")
    def test_expire_unverified_email_senders_removes_old_unverified_senders_and_their_identities(
        self, mock_delete_identity: MagicMock
    ) -> None:
        for email, verified, age_days in [
            ("a@stale.com", False, 15),
            ("b@fresh.com", False, 13),
            ("c@verified.com", True, 30),
        ]:
            sender = Integration.objects.create(
                team=self.team,
                kind="email",
                integration_id=email,
                config={"email": email, "domain": email.split("@")[1], "provider": "ses", "verified": verified},
            )
            Integration.objects.filter(id=sender.id).update(created_at=timezone.now() - timedelta(days=age_days))

        with self.captureOnCommitCallbacks(execute=True):
            expire_unverified_email_senders()

        remaining = Integration.objects.filter(kind="email").values_list("integration_id", flat=True)
        assert set(remaining) == {"b@fresh.com", "c@verified.com"}
        assert [call.args[0] for call in mock_delete_identity.call_args_list] == ["stale.com"]

    @patch("posthog.tasks.integrations.EXPIRED_EMAIL_SENDERS_PER_RUN", 2)
    @patch("posthog.tasks.integrations.delete_ses_identity")
    def test_expire_unverified_email_senders_drains_a_backlog_over_several_runs(
        self, _mock_delete_identity: MagicMock
    ) -> None:
        for index in range(3):
            email = f"a@stale{index}.com"
            sender = Integration.objects.create(
                team=self.team,
                kind="email",
                integration_id=email,
                config={"email": email, "domain": f"stale{index}.com", "provider": "ses", "verified": False},
            )
            Integration.objects.filter(id=sender.id).update(created_at=timezone.now() - timedelta(days=15))

        expire_unverified_email_senders()
        assert Integration.objects.filter(kind="email").count() == 1
        expire_unverified_email_senders()
        assert Integration.objects.filter(kind="email").count() == 0

    @patch("posthog.tasks.integrations.delete_ses_identity")
    def test_expire_unverified_email_senders_keeps_a_sender_that_verifies_during_the_sweep(
        self, mock_delete_identity: MagicMock
    ) -> None:
        config = {"email": "a@late.com", "domain": "late.com", "provider": "ses", "verified": False}
        sender = Integration.objects.create(team=self.team, kind="email", integration_id="a@late.com", config=config)
        Integration.objects.filter(id=sender.id).update(created_at=timezone.now() - timedelta(days=15))
        list_across_teams = IntegrationReader.list_across_teams

        def list_then_verify(reader: IntegrationReader, cross_team_filter: CrossTeamFilter) -> list:
            senders = list_across_teams(reader, cross_team_filter)
            Integration.objects.filter(id=sender.id).update(config={**config, "verified": True})
            return senders

        with (
            patch.object(IntegrationReader, "list_across_teams", list_then_verify),
            self.captureOnCommitCallbacks(execute=True),
        ):
            expire_unverified_email_senders()

        assert Integration.objects.filter(id=sender.id).exists()
        mock_delete_identity.assert_not_called()

    @parameterized.expand(
        [
            ("another_project_still_sends", "other", False, True),
            ("the_same_project_still_sends", "same", False, False),
            ("nobody_sends", None, True, False),
        ]
    )
    def test_delete_ses_identity_if_unused_keeps_only_the_links_of_projects_that_still_send(
        self, _name: str, remaining_sender: Optional[str], identity_deleted: bool, link_removed: bool
    ) -> None:
        if remaining_sender:
            team = self.team if remaining_sender == "same" else Team.objects.create(organization=self.organization)
            Integration.objects.create(team=team, kind="email", config={"domain": "example.com"})
        with (
            patch("posthog.tasks.integrations.delete_ses_identity") as mock_delete,
            patch("posthog.tasks.integrations.remove_ses_tenant_associations") as mock_remove_links,
        ):
            delete_ses_identity_if_unused("example.com", self.team.id)

        assert mock_delete.called is identity_deleted
        assert [call.kwargs["team_ids"] for call in mock_remove_links.call_args_list] == (
            [[self.team.id]] if link_removed else []
        )

    @patch("posthog.tasks.integrations.delete_ses_identity")
    def test_identity_cleanup_waits_for_a_sender_create_in_progress_on_the_domain(
        self, mock_delete_identity: MagicMock
    ) -> None:
        other = connection.get_new_connection(connection.get_connection_params())
        try:
            with other.cursor() as cursor:
                lock_sender_domain(cursor, "example.com")
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '200ms'")
            with pytest.raises(OperationalError, match="lock timeout"):
                delete_ses_identity_if_unused("example.com")
            mock_delete_identity.assert_not_called()
        finally:
            other.rollback()
            other.close()

    def test_branch_refresh_leaves_a_newer_refresh_lock_alone(self) -> None:
        integration = self.create_integration("github", config={"installation_id": "INSTALL"})
        github = GitHubIntegration(integration, source="test", priority=Priority.BATCH)
        lock_key = github._branch_refresh_lock_key("posthog/posthog")
        get_redis_client().set(lock_key, "newer")
        self.addCleanup(get_redis_client().delete, lock_key)

        with patch("posthog.models.integration.github.GitHubIntegration.refresh_branch_cache"):
            refresh_github_branch_cache(str(integration.id), "posthog/posthog", False, "older", self.team.id)

        assert get_redis_client().get(lock_key) == b"newer"
