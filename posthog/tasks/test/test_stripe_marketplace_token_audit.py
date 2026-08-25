from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from posthog.celery_task_names import AUDIT_STRIPE_MARKETPLACE_TOKENS_TASK_NAME, LIVENESS_ALERTED_TASK_NAMES
from posthog.models import Team
from posthog.models.integration import Integration, StripeIntegration
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.tasks.stripe_marketplace_token_audit import audit_stripe_marketplace_tokens_task

ORCHESTRATOR_CLIENT_ID = "orchestrator_client_id"
MARKETPLACE_CLIENT_ID = "marketplace_client_id"


def _oauth_app(client_id: str) -> OAuthApplication:
    return OAuthApplication.objects.create(
        name=f"App {client_id}",
        client_id=client_id,
        client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
        authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
        redirect_uris="https://example.com/callback",
        algorithm="RS256",
    )


@override_settings(
    STRIPE_POSTHOG_OAUTH_CLIENT_ID=ORCHESTRATOR_CLIENT_ID,
    STRIPE_MARKETPLACE_OAUTH_CLIENT_ID=MARKETPLACE_CLIENT_ID,
)
class TestStripeMarketplaceTokenAudit(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.orchestrator = _oauth_app(ORCHESTRATOR_CLIENT_ID)
        self.marketplace = _oauth_app(MARKETPLACE_CLIENT_ID)

    def _stripe_integration(self, team: Team) -> Integration:
        return Integration.objects.create(
            team=team,
            kind="stripe",
            integration_id=f"acct_{team.pk}",
            config={},
            sensitive_config={},
            created_by=self.user,
        )

    def _credentials(self, application: OAuthApplication, scoped_teams: list[int], suffix: str) -> None:
        access_token = OAuthAccessToken.objects.create(
            application=application,
            token=f"access_{suffix}",
            user=self.user,
            expires=timezone.now() + timedelta(days=14),
            scope=StripeIntegration.SCOPES,
            scoped_teams=scoped_teams,
        )
        OAuthRefreshToken.objects.create(
            application=application,
            token=f"refresh_{suffix}",
            user=self.user,
            access_token=access_token,
            scoped_teams=scoped_teams,
        )

    def _run(self) -> int:
        with patch("posthog.tasks.stripe_marketplace_token_audit._publish") as publish:
            audit_stripe_marketplace_tokens_task()
        return publish.call_args[0][1]

    def test_reports_zero_when_marketplace_credentials_are_on_the_marketplace_app(self) -> None:
        self._stripe_integration(self.team)
        self._credentials(self.marketplace, [self.team.pk], "ok")

        self.assertEqual(self._run(), 0)

    def test_counts_single_team_credentials_on_the_orchestrator_app(self) -> None:
        self._stripe_integration(self.team)
        self._credentials(self.orchestrator, [self.team.pk], "leaked")

        self.assertEqual(self._run(), 2)

    def test_ignores_multi_team_provisioning_credentials(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        self._stripe_integration(self.team)
        self._credentials(self.orchestrator, [self.team.pk, other_team.pk], "provisioning")

        self.assertEqual(self._run(), 0)

    def test_ignores_teams_without_a_stripe_integration(self) -> None:
        self._credentials(self.orchestrator, [self.team.pk], "unrelated")

        self.assertEqual(self._run(), 0)

    def test_ignores_expired_access_and_revoked_refresh_credentials(self) -> None:
        self._stripe_integration(self.team)
        access_token = OAuthAccessToken.objects.create(
            application=self.orchestrator,
            token="access_expired",
            user=self.user,
            expires=timezone.now() - timedelta(days=1),
            scope=StripeIntegration.SCOPES,
            scoped_teams=[self.team.pk],
        )
        OAuthRefreshToken.objects.create(
            application=self.orchestrator,
            token="refresh_revoked",
            user=self.user,
            access_token=access_token,
            scoped_teams=[self.team.pk],
            revoked=timezone.now(),
        )

        self.assertEqual(self._run(), 0)

    def test_captures_an_exception_so_the_finding_reaches_error_tracking(self) -> None:
        self._stripe_integration(self.team)
        self._credentials(self.orchestrator, [self.team.pk], "leaked")

        with patch("posthog.tasks.stripe_marketplace_token_audit.capture_exception") as capture:
            with patch("posthog.tasks.stripe_marketplace_token_audit._publish"):
                audit_stripe_marketplace_tokens_task()

        self.assertEqual(capture.call_count, 1)
        self.assertEqual(capture.call_args[0][1]["teams"], [self.team.pk])

    def test_task_name_is_pinned_for_the_liveness_alert(self) -> None:
        self.assertEqual(audit_stripe_marketplace_tokens_task.name, AUDIT_STRIPE_MARKETPLACE_TOKENS_TASK_NAME)
        self.assertIn(AUDIT_STRIPE_MARKETPLACE_TOKENS_TASK_NAME, LIVENESS_ALERTED_TASK_NAMES)

    def test_skips_when_the_orchestrator_application_row_is_absent(self) -> None:
        self.orchestrator.delete()
        self._stripe_integration(self.team)

        with patch("posthog.tasks.stripe_marketplace_token_audit._publish") as publish:
            audit_stripe_marketplace_tokens_task()

        publish.assert_not_called()
