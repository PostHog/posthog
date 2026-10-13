from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from posthog.models import Organization
from posthog.models.identity_provider_config import IdentityProviderConfig
from posthog.models.linked_identity_provider_config import LinkedIdentityProviderConfig
from posthog.models.organization_domain import OrganizationDomain

from ee.models.scim_request_log import SCIMRequestLog


class TestBackfillSCIMRequestLogConfig(BaseTest):
    def setUp(self):
        super().setUp()
        self.config = IdentityProviderConfig.objects.create(organization=self.organization, scim_enabled=True)
        self.domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="example.com",
            verified_at="2024-01-01T00:00:00Z",
        )
        LinkedIdentityProviderConfig.objects.create(
            organization_domain=self.domain, identity_provider_config=self.config
        )
        self.unlinked_domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="unlinked.example.com",
            verified_at="2024-01-01T00:00:00Z",
        )

    def _create_log(self, domain: OrganizationDomain, **kwargs) -> SCIMRequestLog:
        return SCIMRequestLog.objects.create(
            organization_domain=domain,
            request_method="GET",
            request_path="/scim/v2/slug/Users",
            request_headers={},
            response_status=200,
            identity_provider="okta",
            **kwargs,
        )

    def _run(self, **options) -> str:
        out = StringIO()
        call_command("backfill_scim_request_log_config", stdout=out, **options)
        return out.getvalue()

    def test_fills_the_config_from_the_logged_domain(self):
        log = self._create_log(self.domain)

        self._run(batch_size=1)

        log.refresh_from_db()
        assert log.identity_provider_config_id == self.config.id

    def test_leaves_a_log_whose_domain_has_no_config_on_its_domain_key(self):
        log = self._create_log(self.unlinked_domain)

        output = self._run()

        log.refresh_from_db()
        assert log.identity_provider_config_id is None
        assert "1 row(s) left on their domain key" in output

    def test_dry_run_reports_without_writing(self):
        log = self._create_log(self.domain)

        output = self._run(dry_run=True)

        log.refresh_from_db()
        assert log.identity_provider_config_id is None
        assert "1 row(s) would be filled" in output

    def test_rerun_is_a_no_op_and_does_not_move_rows_between_tenants(self):
        other_config = IdentityProviderConfig.objects.create(organization=self.organization, scim_enabled=True)
        already_attributed = self._create_log(self.domain, identity_provider_config=other_config)
        pending = self._create_log(self.domain)

        self._run()
        self._run()

        already_attributed.refresh_from_db()
        pending.refresh_from_db()
        assert already_attributed.identity_provider_config_id == other_config.id
        assert pending.identity_provider_config_id == self.config.id

    def test_organization_scope_limits_the_sweep(self):
        other_organization = Organization.objects.create(name="Other Org")
        other_config = IdentityProviderConfig.objects.create(organization=other_organization, scim_enabled=True)
        other_domain = OrganizationDomain.objects.create(
            organization=other_organization,
            domain="other.example.com",
            verified_at="2024-01-01T00:00:00Z",
        )
        LinkedIdentityProviderConfig.objects.create(
            organization_domain=other_domain, identity_provider_config=other_config
        )
        mine = self._create_log(self.domain)
        theirs = self._create_log(other_domain)

        self._run(organization_id=str(self.organization.id))

        mine.refresh_from_db()
        theirs.refresh_from_db()
        assert mine.identity_provider_config_id == self.config.id
        assert theirs.identity_provider_config_id is None

    def test_start_after_resumes_past_earlier_rows(self):
        logs = sorted([self._create_log(self.domain) for _ in range(3)], key=lambda log: log.id)

        self._run(start_after=str(logs[0].id))

        for log in logs:
            log.refresh_from_db()
        assert [log.identity_provider_config_id for log in logs] == [None, self.config.id, self.config.id]
