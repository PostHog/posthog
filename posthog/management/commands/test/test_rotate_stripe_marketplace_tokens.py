from datetime import timedelta
from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team
from posthog.models.integration import Integration, StripeIntegration
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken


def _oauth_app(client_id: str) -> OAuthApplication:
    return OAuthApplication.objects.create(
        name=f"App {client_id}",
        client_id=client_id,
        client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
        authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
        redirect_uris="https://example.com/callback",
        algorithm="RS256",
    )


class TestRotateStripeMarketplaceTokens(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.new_app = _oauth_app("marketplace_client_id")
        self.old_app = _oauth_app("legacy_client_id")

    def _create_integration_with_token(
        self, team: Team, integration_id: str, application: OAuthApplication, created_by=None
    ) -> tuple[Integration, OAuthAccessToken, OAuthRefreshToken]:
        integration = Integration.objects.create(
            team=team,
            kind="stripe",
            integration_id=integration_id,
            config={},
            sensitive_config={},
            created_by=created_by,
        )
        access_token = OAuthAccessToken.objects.create(
            application=application,
            token=f"access_{integration_id}",
            user=created_by,
            expires=timezone.now() + timedelta(days=14),
            scope=StripeIntegration.SCOPES,
            scoped_teams=[team.pk],
        )
        refresh_token = OAuthRefreshToken.objects.create(
            application=application,
            token=f"refresh_{integration_id}",
            user=created_by,
            access_token=access_token,
            scoped_teams=[team.pk],
        )
        return integration, access_token, refresh_token

    @patch("stripe.StripeClient")
    def test_dry_run_makes_no_changes(self, MockStripeClient) -> None:
        integration, access_token, refresh_token = self._create_integration_with_token(
            self.team, "acct_dry_run", self.old_app, created_by=self.user
        )

        with self.settings(
            STRIPE_MARKETPLACE_OAUTH_CLIENT_ID=self.new_app.client_id,
            STRIPE_POSTHOG_OAUTH_CLIENT_ID=self.old_app.client_id,
        ):
            call_command("rotate_stripe_marketplace_tokens", "--dry-run")

        assert OAuthAccessToken.objects.filter(pk=access_token.pk).exists()
        assert OAuthRefreshToken.objects.filter(pk=refresh_token.pk).exists()
        assert OAuthAccessToken.objects.count() == 1
        MockStripeClient.assert_not_called()

    @patch("stripe.StripeClient")
    def test_real_run_revokes_old_tokens_and_mints_on_marketplace_app(self, MockStripeClient) -> None:
        mock_client = MagicMock()
        MockStripeClient.return_value = mock_client

        integration, old_access, old_refresh = self._create_integration_with_token(
            self.team, "acct_rotate", self.old_app, created_by=self.user
        )

        with self.settings(
            STRIPE_MARKETPLACE_OAUTH_CLIENT_ID=self.new_app.client_id,
            STRIPE_POSTHOG_OAUTH_CLIENT_ID=self.old_app.client_id,
            STRIPE_APP_CLIENT_ID="stripe_app_client_id",
            STRIPE_APP_SECRET_KEY="sk_test",
        ):
            call_command("rotate_stripe_marketplace_tokens")

        assert not OAuthAccessToken.objects.filter(pk=old_access.pk).exists()
        assert not OAuthRefreshToken.objects.filter(pk=old_refresh.pk).exists()

        new_access = OAuthAccessToken.objects.get(application=self.new_app, scoped_teams__contains=[self.team.pk])
        assert new_access.user_id == self.user.id
        assert OAuthRefreshToken.objects.filter(access_token=new_access).exists()

        secret_calls = mock_client.apps.secrets.create.call_args_list
        assert len(secret_calls) == 5
        for call in secret_calls:
            assert call.kwargs["options"] == {"stripe_account": "acct_rotate"}

    def test_skips_integration_with_no_created_by(self) -> None:
        integration = Integration.objects.create(
            team=self.team,
            kind="stripe",
            integration_id="acct_no_owner",
            config={},
            sensitive_config={},
            created_by=None,
        )

        out = StringIO()
        with self.settings(
            STRIPE_MARKETPLACE_OAUTH_CLIENT_ID=self.new_app.client_id,
            STRIPE_POSTHOG_OAUTH_CLIENT_ID=self.old_app.client_id,
        ):
            call_command("rotate_stripe_marketplace_tokens", stdout=out)

        assert integration.created_by is None
        assert OAuthAccessToken.objects.count() == 0
        assert "no created_by user" in out.getvalue()
        assert "Skipped: 1" in out.getvalue()
        assert "Rotated: 0" in out.getvalue()

    @patch("stripe.StripeClient")
    @patch("posthog.management.commands.rotate_stripe_marketplace_tokens.capture_exception")
    def test_one_failure_does_not_block_other_integrations(self, mock_capture, MockStripeClient) -> None:
        mock_client = MagicMock()
        MockStripeClient.return_value = mock_client

        other_team = Team.objects.create(organization=self.organization, name="Other team")
        failing_integration, failing_access, failing_refresh = self._create_integration_with_token(
            self.team, "acct_fails", self.old_app, created_by=self.user
        )
        ok_integration, ok_access, ok_refresh = self._create_integration_with_token(
            other_team, "acct_ok", self.old_app, created_by=self.user
        )

        original_write_secrets = StripeIntegration.write_posthog_secrets

        def flaky_write_posthog_secrets(self, team_id, created_by):
            if self.integration.pk == failing_integration.pk:
                raise Exception("simulated Stripe API failure")
            return original_write_secrets(self, team_id, created_by)

        out = StringIO()
        with (
            self.settings(
                STRIPE_MARKETPLACE_OAUTH_CLIENT_ID=self.new_app.client_id,
                STRIPE_POSTHOG_OAUTH_CLIENT_ID=self.old_app.client_id,
                STRIPE_APP_CLIENT_ID="stripe_app_client_id",
                STRIPE_APP_SECRET_KEY="sk_test",
            ),
            patch.object(StripeIntegration, "write_posthog_secrets", flaky_write_posthog_secrets),
        ):
            call_command("rotate_stripe_marketplace_tokens", stdout=out)

        mock_capture.assert_called_once()

        output = out.getvalue()
        assert "Rotated: 1" in output
        assert "Failed: 1" in output
        assert "simulated Stripe API failure" in output

        # The failing integration keeps a working credential: revocation only happens once the
        # replacement is confirmed live in Stripe. Nothing orphaned is left behind either.
        assert OAuthAccessToken.objects.filter(pk=failing_access.pk).exists()
        assert not OAuthAccessToken.objects.filter(
            application=self.new_app, scoped_teams__contains=[self.team.pk]
        ).exists()

        assert not OAuthAccessToken.objects.filter(pk=ok_access.pk).exists()
        assert OAuthAccessToken.objects.filter(
            application=self.new_app, scoped_teams__contains=[other_team.pk]
        ).exists()

    @patch("stripe.StripeClient")
    @patch("posthog.management.commands.rotate_stripe_marketplace_tokens.capture_exception")
    def test_partial_stripe_write_leaves_both_credentials_in_place(self, mock_capture, MockStripeClient) -> None:
        mock_client = MagicMock()
        MockStripeClient.return_value = mock_client

        def fail_on_refresh_token(params, options):
            if params["name"] == "posthog_refresh_token":
                raise Exception("simulated Stripe API failure")
            return MagicMock()

        mock_client.apps.secrets.create.side_effect = fail_on_refresh_token

        integration, stale_access, stale_refresh = self._create_integration_with_token(
            self.team, "acct_partial", self.old_app, created_by=self.user
        )

        out = StringIO()
        with self.settings(
            STRIPE_MARKETPLACE_OAUTH_CLIENT_ID=self.new_app.client_id,
            STRIPE_POSTHOG_OAUTH_CLIENT_ID=self.old_app.client_id,
            STRIPE_APP_CLIENT_ID="stripe_app_client_id",
            STRIPE_APP_SECRET_KEY="sk_test",
        ):
            call_command("rotate_stripe_marketplace_tokens", stdout=out)

        output = out.getvalue()
        assert "Rotated: 0" in output
        assert "Failed: 1" in output
        assert "needs manual repair" in output

        # Stripe already serves the new token for posthog_access_token, so deleting it would break
        # the customer. The stale token stays too, since it was never confirmed replaced.
        assert OAuthAccessToken.objects.filter(pk=stale_access.pk).exists()
        assert OAuthRefreshToken.objects.filter(pk=stale_refresh.pk).exists()
        assert OAuthAccessToken.objects.filter(application=self.new_app, scoped_teams__contains=[self.team.pk]).exists()

        mock_capture.assert_called_once()

    def test_refuses_when_the_marketplace_id_is_the_orchestrator(self) -> None:
        with self.settings(
            STRIPE_MARKETPLACE_OAUTH_CLIENT_ID=self.old_app.client_id,
            STRIPE_POSTHOG_OAUTH_CLIENT_ID=self.old_app.client_id,
        ):
            with self.assertRaises(CommandError):
                call_command("rotate_stripe_marketplace_tokens")

    @patch("stripe.StripeClient")
    def test_sweeps_a_credential_minted_by_a_refresh_mid_rotation(self, MockStripeClient) -> None:
        mock_client = MagicMock()
        MockStripeClient.return_value = mock_client

        integration, stale_access, stale_refresh = self._create_integration_with_token(
            self.team, "acct_refresh_race", self.old_app, created_by=self.user
        )

        original_write_secrets = StripeIntegration.write_posthog_secrets
        refreshed: dict[str, OAuthAccessToken] = {}

        def refresh_during_write(self, team_id, created_by):
            result = original_write_secrets(self, team_id, created_by)
            # What DOT's refresh path does with the leaked legacy refresh token: a fresh pair on
            # the orchestrator application, created after the rotation snapshotted token ids.
            refreshed["access"] = OAuthAccessToken.objects.create(
                application=stale_access.application,
                token="ph_access_refreshed",
                user=created_by,
                expires=timezone.now() + timedelta(days=14),
                scope="query:read",
                scoped_teams=[team_id],
            )
            OAuthRefreshToken.objects.create(
                application=stale_access.application,
                token="ph_refresh_refreshed",
                user=created_by,
                access_token=refreshed["access"],
                scoped_teams=[team_id],
            )
            return result

        out = StringIO()
        with (
            self.settings(
                STRIPE_MARKETPLACE_OAUTH_CLIENT_ID=self.new_app.client_id,
                STRIPE_POSTHOG_OAUTH_CLIENT_ID=self.old_app.client_id,
                STRIPE_APP_CLIENT_ID="stripe_app_client_id",
                STRIPE_APP_SECRET_KEY="sk_test",
            ),
            patch.object(StripeIntegration, "write_posthog_secrets", refresh_during_write),
        ):
            call_command("rotate_stripe_marketplace_tokens", stdout=out)

        assert "Rotated: 1" in out.getvalue()
        assert not OAuthAccessToken.objects.filter(pk=stale_access.pk).exists()
        assert not OAuthRefreshToken.objects.filter(pk=stale_refresh.pk).exists()
        # The whole point: a snapshot-based delete would have missed this one.
        assert not OAuthAccessToken.objects.filter(pk=refreshed["access"].pk).exists()
        assert not OAuthAccessToken.objects.filter(
            application=self.old_app, scoped_teams__contains=[self.team.pk]
        ).exists()
        assert OAuthAccessToken.objects.filter(application=self.new_app, scoped_teams__contains=[self.team.pk]).exists()

    @patch("stripe.StripeClient")
    @patch("posthog.models.integration.stripe.lock_oauth_connection")
    def test_takes_the_connection_lock_before_deleting(self, mock_lock, MockStripeClient) -> None:
        mock_client = MagicMock()
        MockStripeClient.return_value = mock_client

        integration, stale_access, _ = self._create_integration_with_token(
            self.team, "acct_lock", self.old_app, created_by=self.user
        )

        deleted_while_unlocked: list[bool] = []
        original_delete = OAuthAccessToken.delete

        def recording_delete(instance, *args, **kwargs):
            deleted_while_unlocked.append(not mock_lock.called)
            return original_delete(instance, *args, **kwargs)

        with (
            self.settings(
                STRIPE_MARKETPLACE_OAUTH_CLIENT_ID=self.new_app.client_id,
                STRIPE_POSTHOG_OAUTH_CLIENT_ID=self.old_app.client_id,
                STRIPE_APP_CLIENT_ID="stripe_app_client_id",
                STRIPE_APP_SECRET_KEY="sk_test",
            ),
            patch.object(OAuthAccessToken, "delete", recording_delete),
        ):
            call_command("rotate_stripe_marketplace_tokens", stdout=StringIO())

        # Row locks alone let a mid-sweep refresh survive, so the advisory lock has to come first.
        locked_pairs = {(call.kwargs["user_id"], call.kwargs["application_id"]) for call in mock_lock.call_args_list}
        assert (self.user.pk, self.old_app.id) in locked_pairs
        assert (self.user.pk, self.new_app.id) in locked_pairs
        assert not any(deleted_while_unlocked)

    @patch("stripe.StripeClient")
    def test_sweeps_a_refresh_token_no_access_token_points_at(self, MockStripeClient) -> None:
        mock_client = MagicMock()
        MockStripeClient.return_value = mock_client

        integration, stale_access, _ = self._create_integration_with_token(
            self.team, "acct_unlinked", self.old_app, created_by=self.user
        )
        # What the Stripe provisioning refresh leaves behind: the superseded row keeps no link to
        # any access token, so a link-based sweep cannot see it.
        unlinked = OAuthRefreshToken.objects.create(
            application=self.old_app,
            token="ph_refresh_unlinked",
            user=self.user,
            access_token=None,
            scoped_teams=[self.team.pk],
        )

        with self.settings(
            STRIPE_MARKETPLACE_OAUTH_CLIENT_ID=self.new_app.client_id,
            STRIPE_POSTHOG_OAUTH_CLIENT_ID=self.old_app.client_id,
            STRIPE_APP_CLIENT_ID="stripe_app_client_id",
            STRIPE_APP_SECRET_KEY="sk_test",
        ):
            call_command("rotate_stripe_marketplace_tokens", stdout=StringIO())

        assert not OAuthRefreshToken.objects.filter(pk=unlinked.pk).exists()
        assert not OAuthAccessToken.objects.filter(pk=stale_access.pk).exists()
        assert OAuthAccessToken.objects.filter(application=self.new_app, scoped_teams__contains=[self.team.pk]).exists()

    @patch("stripe.StripeClient")
    def test_a_write_that_never_reaches_stripe_leaves_no_credential(self, MockStripeClient) -> None:
        mock_client = MagicMock()
        mock_client.apps.secrets.create.side_effect = Exception("simulated Stripe API failure")
        MockStripeClient.return_value = mock_client

        integration, stale_access, stale_refresh = self._create_integration_with_token(
            self.team, "acct_total_failure", self.old_app, created_by=self.user
        )

        out = StringIO()
        with self.settings(
            STRIPE_MARKETPLACE_OAUTH_CLIENT_ID=self.new_app.client_id,
            STRIPE_POSTHOG_OAUTH_CLIENT_ID=self.old_app.client_id,
            STRIPE_APP_CLIENT_ID="stripe_app_client_id",
            STRIPE_APP_SECRET_KEY="sk_test",
        ):
            call_command("rotate_stripe_marketplace_tokens", stdout=out)

        assert "Failed: 1" in out.getvalue()
        # The customer keeps what Stripe is still serving, and the unusable mint is gone.
        assert OAuthAccessToken.objects.filter(pk=stale_access.pk).exists()
        assert OAuthRefreshToken.objects.filter(pk=stale_refresh.pk).exists()
        assert not OAuthAccessToken.objects.filter(
            application=self.new_app, scoped_teams__contains=[self.team.pk]
        ).exists()

    @patch("stripe.StripeClient")
    def test_leaves_a_credential_shared_with_another_team(self, MockStripeClient) -> None:
        mock_client = MagicMock()
        MockStripeClient.return_value = mock_client

        other_team = Team.objects.create(organization=self.organization, name="Sibling team")
        integration, stale_access, _ = self._create_integration_with_token(
            self.team, "acct_shared", self.old_app, created_by=self.user
        )
        # A provisioning credential can cover several teams at once. Rotating one of them must
        # not take the others down with it.
        shared = OAuthAccessToken.objects.create(
            application=self.old_app,
            token="ph_access_shared",
            user=self.user,
            expires=timezone.now() + timedelta(days=14),
            scope="query:read",
            scoped_teams=[self.team.pk, other_team.pk],
        )

        with self.settings(
            STRIPE_MARKETPLACE_OAUTH_CLIENT_ID=self.new_app.client_id,
            STRIPE_POSTHOG_OAUTH_CLIENT_ID=self.old_app.client_id,
            STRIPE_APP_CLIENT_ID="stripe_app_client_id",
            STRIPE_APP_SECRET_KEY="sk_test",
        ):
            call_command("rotate_stripe_marketplace_tokens", stdout=StringIO())

        # The sibling keeps working, and this team can no longer reach anything through it.
        shared.refresh_from_db()
        assert shared.scoped_teams == [other_team.pk]
        assert not OAuthAccessToken.objects.filter(pk=stale_access.pk).exists()

    @patch("stripe.StripeClient")
    def test_a_multi_team_legacy_credential_cannot_keep_reaching_this_team(self, MockStripeClient) -> None:
        mock_client = MagicMock()
        MockStripeClient.return_value = mock_client

        other_team = Team.objects.create(organization=self.organization, name="Second team")
        integration, _, _ = self._create_integration_with_token(
            self.team, "acct_multi", self.old_app, created_by=self.user
        )
        # What a leaked legacy credential looks like after the provisioning refresh recomputes
        # its scope: still on the orchestrator application, now covering more than one team.
        widened = OAuthAccessToken.objects.create(
            application=self.old_app,
            token="ph_access_widened",
            user=self.user,
            expires=timezone.now() + timedelta(days=14),
            scope="query:read",
            scoped_teams=[self.team.pk, other_team.pk],
        )
        widened_refresh = OAuthRefreshToken.objects.create(
            application=self.old_app,
            token="ph_refresh_widened",
            user=self.user,
            access_token=widened,
            scoped_teams=[self.team.pk, other_team.pk],
        )

        with self.settings(
            STRIPE_MARKETPLACE_OAUTH_CLIENT_ID=self.new_app.client_id,
            STRIPE_POSTHOG_OAUTH_CLIENT_ID=self.old_app.client_id,
            STRIPE_APP_CLIENT_ID="stripe_app_client_id",
            STRIPE_APP_SECRET_KEY="sk_test",
        ):
            call_command("rotate_stripe_marketplace_tokens", stdout=StringIO())

        widened.refresh_from_db()
        widened_refresh.refresh_from_db()
        assert self.team.pk not in widened.scoped_teams
        assert self.team.pk not in widened_refresh.scoped_teams
        assert widened.scoped_teams == [other_team.pk]

    @parameterized.expand(
        [
            ("client_id_unset", ""),
            ("client_id_set_but_no_matching_app", "not_yet_created_client_id"),
        ]
    )
    def test_refuses_to_run_when_not_configured(self, _name, client_id) -> None:
        with self.settings(STRIPE_MARKETPLACE_OAUTH_CLIENT_ID=client_id):
            with self.assertRaises(CommandError):
                call_command("rotate_stripe_marketplace_tokens")
