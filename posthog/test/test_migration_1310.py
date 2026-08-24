from typing import Any

from posthog.test.base import NonAtomicTestMigrations


# Non-atomic so a later posthog migration with a CONCURRENTLY index doesn't break the rewind.
class ProvisioningRateLimitOverridesMigrationTest(NonAtomicTestMigrations):
    migrate_from = "1309_integration_kind_ext_idx"
    migrate_to = "1310_provisioning_rate_limit_overrides"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        OAuthApplication = apps.get_model("posthog", "OAuthApplication")
        self.OAuthApplication = OAuthApplication

        def create(client_id: str, config: dict) -> Any:
            return OAuthApplication.objects.create(
                name=client_id,
                client_id=client_id,
                client_secret="",
                client_type="confidential",
                authorization_grant_type="authorization-code",
                redirect_uris="https://example.com/callback",
                algorithm="RS256",
                _provisioning_config=config,
            )

        # Tier-sourced: the persisted tier value goes, other keys are normalized while
        # this row is being written anyway.
        self.tiered = create(
            "tiered",
            {
                "active": True,
                "rate_limits": {
                    "account_requests": 100,
                    "resource_creates": 5,
                    "wizard_runs": 0,
                    "token_exchanges": None,
                },
                "rate_limit_source": "default_verified",
            },
        )
        # Not tier-sourced, so the migration leaves it alone. 1274 wrote a config onto
        # every OAuthApplication, so rewriting these rows would mean rewriting the table;
        # the read-path validator normalizes them instead.
        self.admin_set = create(
            "admin_set",
            {
                "active": True,
                "rate_limits": {"account_requests": 250, "wizard_runs": 0},
                "rate_limit_source": "admin",
            },
        )
        self.legacy = create("legacy", {"active": True, "rate_limits": {"account_requests": 42}})
        self.untouched = create("untouched", {})

    def test_only_tier_sourced_rows_are_rewritten(self) -> None:
        tiered = self.OAuthApplication.objects.get(pk=self.tiered.pk)._provisioning_config
        assert tiered["rate_limits"] == {"resource_creates": 5, "wizard_runs": -1}
        assert "rate_limit_source" not in tiered

        admin_set = self.OAuthApplication.objects.get(pk=self.admin_set.pk)._provisioning_config
        assert admin_set["rate_limits"] == {"account_requests": 250, "wizard_runs": 0}
        assert admin_set["rate_limit_source"] == "admin"

        legacy = self.OAuthApplication.objects.get(pk=self.legacy.pk)._provisioning_config
        assert legacy["rate_limits"] == {"account_requests": 42}

        assert self.OAuthApplication.objects.get(pk=self.untouched.pk)._provisioning_config == {}
