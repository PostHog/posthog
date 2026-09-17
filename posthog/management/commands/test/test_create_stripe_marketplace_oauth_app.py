from io import StringIO

import pytest
from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.models.integration import StripeIntegration
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig

MARKETPLACE_CLIENT_ID = "marketplace_client_id"
ORCHESTRATOR_CLIENT_ID = "orchestrator_client_id"


class TestCreateStripeMarketplaceOauthApp(BaseTest):
    def test_creates_the_application_locked_down(self):
        call_command("create_stripe_marketplace_oauth_app", client_id=MARKETPLACE_CLIENT_ID, stdout=StringIO())

        app = OAuthApplication.objects.get(client_id=MARKETPLACE_CLIENT_ID)
        assert app.client_type == OAuthApplication.CLIENT_PUBLIC
        assert app.provisioning.can_issue_deep_links is False
        assert set(app.ceiling_scopes) == set(StripeIntegration.SCOPES.split())

    def test_refuses_the_orchestrator_client_id(self):
        with self.settings(STRIPE_POSTHOG_OAUTH_CLIENT_ID=ORCHESTRATOR_CLIENT_ID):
            with pytest.raises(CommandError):
                call_command("create_stripe_marketplace_oauth_app", client_id=ORCHESTRATOR_CLIENT_ID, stdout=StringIO())

        assert not OAuthApplication.objects.filter(client_id=ORCHESTRATOR_CLIENT_ID).exists()

    def test_reconciles_an_application_that_drifted(self):
        drifted = OAuthApplication.objects.create(
            client_id=MARKETPLACE_CLIENT_ID,
            name="wrong name",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://localhost",
            algorithm="RS256",
            is_provisioning_partner=True,
            scopes=["insight:read"],
            optional_scopes=["person:read"],
        )
        drifted.update_provisioning(
            active=True,
            can_issue_deep_links=True,
            can_provision_resources=True,
            can_create_accounts=True,
            can_use_github_grants=True,
            can_start_wizard_runs=True,
            skip_existing_user_consent=True,
        )

        call_command("create_stripe_marketplace_oauth_app", client_id=MARKETPLACE_CLIENT_ID, stdout=StringIO())

        app = OAuthApplication.objects.get(client_id=MARKETPLACE_CLIENT_ID)
        assert app.client_type == OAuthApplication.CLIENT_PUBLIC
        assert app.is_provisioning_partner is False
        assert app.provisioning == ProvisioningConfig()
        assert app.optional_scopes == []
        assert set(app.ceiling_scopes) == set(StripeIntegration.SCOPES.split())

    def test_refuses_a_client_id_this_region_does_not_run_on(self):
        with self.settings(STRIPE_MARKETPLACE_OAUTH_CLIENT_ID="a_different_client_id"):
            with pytest.raises(CommandError):
                call_command("create_stripe_marketplace_oauth_app", client_id=MARKETPLACE_CLIENT_ID, stdout=StringIO())

        assert not OAuthApplication.objects.filter(client_id=MARKETPLACE_CLIENT_ID).exists()

    def test_dry_run_writes_nothing(self):
        call_command(
            "create_stripe_marketplace_oauth_app",
            client_id=MARKETPLACE_CLIENT_ID,
            dry_run=True,
            stdout=StringIO(),
        )

        assert not OAuthApplication.objects.filter(client_id=MARKETPLACE_CLIENT_ID).exists()
