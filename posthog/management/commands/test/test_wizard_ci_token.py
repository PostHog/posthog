from datetime import timedelta
from io import StringIO

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from posthog.models import OAuthAccessToken, OAuthApplication, User

_WIZARD_CLIENT_ID = "wizard-ci-client-id"


@override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID=_WIZARD_CLIENT_ID, WIZARD_GATEWAY_CLIENT_IDS=[_WIZARD_CLIENT_ID])
class TestWizardCiTokenCommand(BaseTest):
    def _create_wizard_app(self, scopes: list[str]) -> OAuthApplication:
        return OAuthApplication.objects.create(
            client_id=_WIZARD_CLIENT_ID,
            name="PostHog Wizard",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8237/callback",
            algorithm="RS256",
            scopes=scopes,
        )

    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("wizard_ci_token", "--email", self.user.email, "--team", str(self.team.id), *args, stdout=out)
        return out.getvalue()

    def test_mints_a_long_lived_token_under_the_wizard_app(self) -> None:
        app = self._create_wizard_app(["project:read", "llm_gateway:read"])

        out = self._run("--days", "30")

        token = out.strip().splitlines()[-1]
        assert token.startswith("pha_")
        row = OAuthAccessToken.objects.get(token=token)
        assert row.application_id == app.id
        assert row.user_id == self.user.id
        assert row.scoped_teams == [self.team.id]
        assert "llm_gateway:read" in row.scope.split()
        # Not the mint helper's six hours: the smoke test runs for months.
        assert row.expires > timezone.now() + timedelta(days=29, hours=23)
        assert row.expires <= timezone.now() + timedelta(days=30)

    def test_the_lifetime_is_bounded(self) -> None:
        self._create_wizard_app(["project:read", "llm_gateway:read"])
        for days in ("0", "731"):
            with pytest.raises(CommandError, match="--days"):
                self._run("--days", days)
        assert not OAuthAccessToken.objects.exists()

    def test_refuses_a_user_outside_the_teams_organization(self) -> None:
        self._create_wizard_app(["project:read", "llm_gateway:read"])
        outsider = User.objects.create(email="outsider@example.com")
        out = StringIO()

        with pytest.raises(CommandError, match="not a member"):
            call_command("wizard_ci_token", "--email", outsider.email, "--team", str(self.team.id), stdout=out)
        assert not OAuthAccessToken.objects.exists()

    def test_refuses_when_the_app_cannot_grant_the_gateway_scope(self) -> None:
        # A token without llm_gateway:read mints nothing at the gateway, so it
        # must not be issued at all.
        self._create_wizard_app(["project:read"])

        with pytest.raises(CommandError, match="llm_gateway:read"):
            self._run()
        assert not OAuthAccessToken.objects.exists()

    @override_settings(WIZARD_GATEWAY_CLIENT_IDS=["some-other-app"])
    def test_refuses_when_the_app_is_not_a_mint_client(self) -> None:
        self._create_wizard_app(["project:read", "llm_gateway:read"])

        with pytest.raises(CommandError, match="not_wizard_app"):
            self._run()
        assert not OAuthAccessToken.objects.exists()

    @patch("posthog.temporal.oauth.wizard_identity_blocked", return_value=True)
    def test_refuses_a_blocked_identity(self, mock_blocked) -> None:
        self._create_wizard_app(["project:read", "llm_gateway:read"])

        with pytest.raises(CommandError, match="blocked"):
            self._run()
        assert not OAuthAccessToken.objects.exists()

    def test_refuses_without_a_wizard_app(self) -> None:
        with pytest.raises(CommandError, match="Wizard app not found"):
            self._run()
