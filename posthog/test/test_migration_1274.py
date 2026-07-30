from typing import Any

import pytest
from posthog.test.base import TestMigrations

from parameterized import parameterized

from posthog.models.oauth_provisioning import ProvisioningConfig

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class BackfillProvisioningConfigMigrationTest(TestMigrations):
    migrate_from = "1273_oauth_provisioning_config"
    migrate_to = "1274_backfill_oauth_provisioning_config"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        OAuthApplication = apps.get_model("posthog", "OAuthApplication")
        self.OAuthApplication = OAuthApplication

        # A partner PostHog vouched for, carrying a partner type and a custom quota.
        self.vouched = self._create_app(
            "vouched",
            is_provisioning_partner=True,
            provisioning_partner_type="wizard",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
            provisioning_can_issue_deep_links=True,
            provisioning_rate_limit_account_requests=250,
            provisioning_rate_limit_account_requests_source="admin",
        )
        # A CIMD client that registered itself: partner, but nobody vouched for it.
        self.self_registered = self._create_app(
            "self_registered",
            is_cimd_client=True,
            cimd_metadata_url="https://selfreg.example.com/.well-known/oauth-client-metadata.json",
            is_provisioning_partner=True,
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )
        # An admin-created partner whose type field was simply left blank.
        self.blank_type = self._create_app(
            "blank_type",
            is_provisioning_partner=True,
            provisioning_active=True,
            provisioning_can_provision_resources=True,
        )
        # A self-registered partner an admin killed: flag cleared, kill switch set, deactivated.
        # None of that shows up in the three columns that used to select rows for this backfill.
        self.killed = self._create_app(
            "killed",
            is_cimd_client=True,
            cimd_metadata_url="https://killed.example.com/.well-known/oauth-client-metadata.json",
            provisioning_disabled=True,
        )
        # Capabilities that older migrations granted keyed on provisioning_auth_method and
        # client_id, on a row that 1268 did not make a partner.
        self.legacy = self._create_app(
            "legacy",
            provisioning_can_issue_deep_links=True,
            provisioning_issues_personal_api_key=True,
        )
        # An ordinary OAuth app that has nothing to do with provisioning.
        self.plain = self._create_app("plain")

    def _create_app(self, slug: str, **fields: Any):
        return self.OAuthApplication.objects.create(
            name=f"App {slug}",
            client_id=f"client-{slug}",
            client_secret="",
            client_type="confidential",
            authorization_grant_type="authorization-code",
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            **fields,
        )

    @parameterized.expand(
        [
            # A partner type was the old github-grants gate, so it carries over as the grant.
            ("vouched", "can_use_github_grants", True),
            # Wizard runs were ungated before; a vouched-for partner keeps them.
            ("vouched", "can_start_wizard_runs", True),
            ("vouched", "can_issue_deep_links", True),
            # Self-registration never vouched for anything, so both elevated capabilities go.
            ("self_registered", "can_use_github_grants", False),
            ("self_registered", "can_start_wizard_runs", False),
            # Still allowed to do the ordinary provisioning it was already doing.
            ("self_registered", "can_create_accounts", True),
            ("self_registered", "active", True),
            # Non-CIMD apps only exist because an admin made them, which is what the old gate
            # treated as vouched-for. Preserved so a blank type doesn't lock one out.
            ("blank_type", "can_use_github_grants", True),
            # Wizard runs had no such carve-out, and no partner type means no grant.
            ("blank_type", "can_start_wizard_runs", False),
            # The kill switch is the one capability whose default fails open, so a row that
            # carries it has to be backfilled however unconfigured it otherwise looks - or the
            # next CIMD registration re-grants the partner everything.
            ("killed", "disabled", True),
            # These two fail closed instead, so losing them silently breaks a live integration.
            ("legacy", "can_issue_deep_links", True),
            ("legacy", "issues_personal_api_key", True),
            # Ordinary OAuth apps are the bulk of the table and never a provisioning partner, so
            # an unfiltered backfill must not hand them either capability that reads permissively
            # off an unconfigured row - the old gate let anything non-CIMD through, and
            # provisioning_can_provision_resources was added with default=True.
            ("plain", "can_use_github_grants", False),
            ("plain", "can_provision_resources", False),
            # And the partners that do hold it have to keep it.
            ("vouched", "can_provision_resources", True),
        ]
    )
    def test_capability_backfill(self, app_attr: str, key: str, expected: bool) -> None:
        app = self.OAuthApplication.objects.get(pk=getattr(self, app_attr).pk)
        assert app._provisioning_config[key] is expected

    def test_rate_limits_and_source_carry_over(self) -> None:
        config = self.OAuthApplication.objects.get(pk=self.vouched.pk)._provisioning_config
        assert config["rate_limits"]["account_requests"] == 250
        assert config["rate_limit_source"] == "admin"

    def test_non_partner_app_grants_nothing(self) -> None:
        # Every row is backfilled, so what keeps an ordinary OAuth app harmless is the mapping
        # rather than being skipped: its config has to mean the same as the column's {} default.
        config = self.OAuthApplication.objects.get(pk=self.plain.pk)._provisioning_config
        assert ProvisioningConfig.model_validate(config) == ProvisioningConfig()
