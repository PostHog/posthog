from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken, revoke_oauth_session
from posthog.models.user import User
from posthog.tasks.wizard_blocklist import (
    SweepResult,
    revoke_blocklisted_gateway_credentials,
    sweep_blocklisted_gateway_credentials,
)


class TestSweepBlocklistedGatewayCredentials(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.application = OAuthApplication.objects.create(
            name="Wizard",
            client_id="wizard_client_id",
            client_secret="wizard_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            user=self.user,
            hash_client_secret=True,
            algorithm="RS256",
        )

    def _token(
        self,
        *,
        token: str,
        scope: str = "llm_gateway:read",
        expired: bool = False,
        user: User | None = None,
        scoped_organizations: list[str] | None = None,
    ) -> OAuthAccessToken:
        owner = user or self.user
        expires = timezone.now() + (timedelta(hours=-1) if expired else timedelta(hours=1))
        access_token = OAuthAccessToken.objects.create(
            user=owner,
            application=self.application,
            token=token,
            scope=scope,
            expires=expires,
            scoped_organizations=scoped_organizations,
        )
        OAuthRefreshToken.objects.create(
            user=owner, application=self.application, token=f"refresh_{token}", access_token=access_token
        )
        return access_token

    @patch("posthog.tasks.wizard_blocklist.wizard_identity_blocked", return_value=True)
    def test_a_blocked_user_loses_the_access_and_refresh_token(self, mock_blocked: MagicMock) -> None:
        self._token(token="live_token")

        result = sweep_blocklisted_gateway_credentials()

        assert (result.blocked_users, result.revoked_sessions) == (1, 1)
        # Without the refresh token a ban only holds until the next refresh.
        assert not OAuthAccessToken.objects.filter(application=self.application).exists()
        assert not OAuthRefreshToken.objects.filter(application=self.application).exists()

    @patch("posthog.tasks.wizard_blocklist.wizard_identity_blocked", return_value=False)
    def test_an_unlisted_user_keeps_their_credentials(self, mock_blocked: MagicMock) -> None:
        self._token(token="live_token")

        assert sweep_blocklisted_gateway_credentials() == SweepResult()
        assert OAuthAccessToken.objects.filter(application=self.application).exists()

    @patch("posthog.tasks.wizard_blocklist.wizard_identity_blocked", return_value=True)
    def test_a_wildcard_token_is_a_candidate(self, mock_blocked: MagicMock) -> None:
        # The legacy gateway authenticates a bare `*`, so enumerating only the
        # literal scope leaves it live.
        self._token(token="wildcard_token", scope="*")

        assert sweep_blocklisted_gateway_credentials() == SweepResult(blocked_users=1, revoked_sessions=1)
        assert not OAuthAccessToken.objects.filter(token="wildcard_token").exists()

    @patch("posthog.tasks.wizard_blocklist.wizard_identity_blocked", return_value=True)
    def test_a_credential_without_the_gateway_scope_is_untouched(self, mock_blocked: MagicMock) -> None:
        self._token(token="insight_token", scope="insight:read")

        assert sweep_blocklisted_gateway_credentials() == SweepResult()
        assert OAuthAccessToken.objects.filter(token="insight_token").exists()
        # Nothing to revoke means nothing to ask about.
        mock_blocked.assert_not_called()

    @patch("posthog.tasks.wizard_blocklist.wizard_identity_blocked", return_value=True)
    def test_an_expired_access_token_still_reaches_its_live_refresh_token(self, mock_blocked: MagicMock) -> None:
        # 7-day access against a 30-day refresh token: selecting only live rows
        # leaves a dormant account banned in name only.
        self._token(token="expired_token", expired=True)

        assert sweep_blocklisted_gateway_credentials() == SweepResult(blocked_users=1, revoked_sessions=1)
        assert not OAuthRefreshToken.objects.filter(application=self.application).exists()

    @patch("posthog.tasks.wizard_blocklist.wizard_identity_blocked", return_value=True)
    def test_many_tokens_for_one_app_are_one_revoke_and_one_flag_read(self, mock_blocked: MagicMock) -> None:
        self._token(token="token_one")
        self._token(token="token_two")

        # revoked_sessions is the length of the set the dedupe maintains, so it
        # reads 1 whether or not the guard ran.
        with patch("posthog.tasks.wizard_blocklist.revoke_oauth_session", wraps=revoke_oauth_session) as mock_revoke:
            result = sweep_blocklisted_gateway_credentials()

        assert (result.blocked_users, result.revoked_sessions) == (1, 1)
        assert mock_revoke.call_count == 1
        assert mock_blocked.call_count == 1
        assert not OAuthAccessToken.objects.filter(application=self.application).exists()

    @patch("posthog.tasks.wizard_blocklist._MAX_REVOCATIONS_PER_RUN", 1)
    @patch("posthog.tasks.wizard_blocklist.wizard_identity_blocked", return_value=True)
    def test_a_capped_run_says_so_instead_of_reporting_a_finished_estate(self, mock_blocked: MagicMock) -> None:
        other = User.objects.create_and_join(self.organization, "capped@example.com", None)
        second_app = OAuthApplication.objects.create(
            name="Wizard two",
            client_id="wizard_client_id_two",
            client_secret="wizard_client_secret_two",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            user=self.user,
            hash_client_secret=True,
            algorithm="RS256",
        )
        self._token(token="first_pair")
        OAuthAccessToken.objects.create(
            user=other,
            application=second_app,
            token="second_pair",
            scope="llm_gateway:read",
            expires=timezone.now() + timedelta(hours=1),
        )

        result = sweep_blocklisted_gateway_credentials()

        assert result.capped is True
        assert result.revoked_sessions == 1
        # The backlog survives for the next tick.
        assert OAuthAccessToken.objects.filter(token="second_pair").exists()

    @patch("posthog.tasks.wizard_blocklist.wizard_identity_blocked", return_value=True)
    def test_an_expired_token_with_no_refresh_token_is_not_a_candidate(self, mock_blocked: MagicMock) -> None:
        # Sandbox tokens carry this scope, have no refresh token and are kept 30
        # days, so reading them buys no reachability.
        OAuthAccessToken.objects.create(
            user=self.user,
            application=self.application,
            token="expired_no_refresh",
            scope="llm_gateway:read",
            expires=timezone.now() - timedelta(hours=1),
        )

        assert sweep_blocklisted_gateway_credentials() == SweepResult()
        mock_blocked.assert_not_called()

    def test_the_verdict_is_asked_per_organization_not_once_per_user(self) -> None:
        # A user-keyed memo would answer for whichever row the scan read first.
        self._token(token="org_a", scoped_organizations=["11111111-1111-4111-8111-111111111111"])
        self._token(token="org_b", scoped_organizations=["22222222-2222-4222-8222-222222222222"])

        with patch(
            "posthog.tasks.wizard_blocklist.wizard_identity_blocked",
            side_effect=lambda **kwargs: "22222222-2222-4222-8222-222222222222" in kwargs["organization_ids"],
        ) as mock_blocked:
            result = sweep_blocklisted_gateway_credentials()

        assert mock_blocked.call_count == 2
        assert result.blocked_users == 1

    def test_a_credential_spanning_several_organizations_is_reached_by_a_ban_on_one(self) -> None:
        # A first-party wizard grant is scoped to every organization its user
        # belongs to, so a sole-organization reading would answer "" and miss.
        self._token(
            token="multi_org",
            scoped_organizations=[
                "11111111-1111-4111-8111-111111111111",
                "22222222-2222-4222-8222-222222222222",
            ],
        )

        with patch(
            "posthog.tasks.wizard_blocklist.wizard_identity_blocked",
            side_effect=lambda **kwargs: "22222222-2222-4222-8222-222222222222" in kwargs["organization_ids"],
        ):
            result = sweep_blocklisted_gateway_credentials()

        assert result.revoked_sessions == 1
        assert not OAuthAccessToken.objects.filter(token="multi_org").exists()

    def test_only_the_blocked_user_loses_their_credentials(self) -> None:
        other = User.objects.create_and_join(self.organization, "other@example.com", None)
        self._token(token="blocked_token")
        self._token(token="other_token", user=other)

        with patch(
            "posthog.tasks.wizard_blocklist.wizard_identity_blocked",
            side_effect=lambda **kwargs: kwargs["distinct_id"] == str(self.user.distinct_id),
        ):
            result = sweep_blocklisted_gateway_credentials()

        # A verdict cache keyed on anything but the user takes both or neither.
        assert (result.blocked_users, result.revoked_sessions) == (1, 1)
        assert not OAuthAccessToken.objects.filter(token="blocked_token").exists()
        assert OAuthAccessToken.objects.filter(token="other_token").exists()

    @patch("posthog.tasks.wizard_blocklist.record_blocklist_outcome")
    @patch("posthog.tasks.wizard_blocklist.blocklist_flag_defined", return_value=False)
    def test_a_run_with_no_flag_defined_reports_itself(self, mock_defined: MagicMock, mock_record: MagicMock) -> None:
        # A lost definitions cache looks the same as no ban list, so the skipped
        # run has to reach the counter.
        self._token(token="untouched")

        revoke_blocklisted_gateway_credentials()

        mock_record.assert_called_once_with("revoke_sweep", "unconfigured")
        assert OAuthAccessToken.objects.filter(token="untouched").exists()
