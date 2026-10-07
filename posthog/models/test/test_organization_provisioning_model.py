from posthog.test.base import BaseTest

from django.db import transaction
from django.db.utils import IntegrityError
from django.test import TestCase

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.oauth import OAuthApplication
from posthog.models.organization import Organization
from posthog.models.organization_provisioning import OrganizationProvisioning

from ee.billing.billing_manager import get_billing_lock_partner


class TestOrganizationProvisioningFields(TestCase):
    organization: Organization
    application: OAuthApplication

    @classmethod
    def setUpTestData(cls) -> None:
        cls.organization = Organization.objects.create(name="Example organization")
        cls.application = OAuthApplication.objects.create(
            client_id="example-partner",
            name="Example partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            is_provisioning_partner=True,
        )

    def test_setting_provisioning_application_logs_its_identity(self) -> None:
        self.organization.provisioning_source = Organization.ProvisioningSource.PROVISIONING_API
        self.organization.provisioning_application = self.application
        self.organization.save(update_fields=["provisioning_source", "provisioning_application"])

        log = ActivityLog.objects.get(organization_id=self.organization.id, scope="Organization", activity="updated")
        assert log.detail is not None
        change = next(change for change in log.detail["changes"] if change["field"] == "provisioning_application")
        assert change["action"] == "created"
        assert change["after"] == {"id": str(self.application.id), "name": self.application.name}

    @parameterized.expand(
        [
            ("application_without_source", None, True),
            ("provisioning_api_without_application", "provisioning_api", False),
            ("stripe_projects_without_application", "stripe_projects", False),
            ("vercel_with_application", "vercel", True),
            ("unknown_source_with_application", "unknown", True),
            ("unknown_source_without_application", "unknown", False),
        ]
    )
    def test_rejects_inconsistent_provisioning_fields(
        self, _name: str, source: str | None, with_application: bool
    ) -> None:
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Organization.objects.filter(pk=self.organization.pk).update(
                provisioning_source=source,
                provisioning_application=self.application if with_application else None,
            )

    @parameterized.expand(
        [
            ("provisioning_api", "provisioning_api", True, None, True),
            ("stripe_projects", "stripe_projects", True, None, True),
            ("non_paying_application", "provisioning_api", False, None, False),
            ("vercel", "vercel", False, None, False),
            ("unprovisioned", None, False, None, False),
            ("self_billed", "provisioning_api", True, "cus_example", False),
        ]
    )
    def test_billing_uses_organization_attribution(
        self,
        _name: str,
        source: str | None,
        pays_for_customers: bool,
        customer_id: str | None,
        expected: bool,
    ) -> None:
        self.application.update_provisioning(pays_for_customers=pays_for_customers)
        self.organization.provisioning_source = source
        self.organization.provisioning_application = (
            self.application if source in {"provisioning_api", "stripe_projects"} else None
        )
        self.organization.customer_id = customer_id
        self.organization.save(update_fields=["provisioning_source", "provisioning_application", "customer_id"])

        assert get_billing_lock_partner(self.organization) == (self.application if expected else None)


class TestOrganizationProvisioningModel(BaseTest):
    @parameterized.expand(
        [
            ("provisioning_api_with_application", OrganizationProvisioning.Partner.PROVISIONING_API, True, True),
            ("stripe_projects_with_application", OrganizationProvisioning.Partner.STRIPE_PROJECTS, True, True),
            ("stripe_projects_without_application", OrganizationProvisioning.Partner.STRIPE_PROJECTS, False, False),
            ("vercel_without_application", OrganizationProvisioning.Partner.VERCEL, False, True),
            ("provisioning_api_without_application", OrganizationProvisioning.Partner.PROVISIONING_API, False, False),
            ("vercel_with_application", OrganizationProvisioning.Partner.VERCEL, True, False),
            ("unknown_partner_with_application", "verce", True, False),
        ]
    )
    def test_application_must_match_partner(
        self, _name: str, partner: OrganizationProvisioning.Partner | str, with_application: bool, allowed: bool
    ) -> None:
        application = (
            OAuthApplication.objects.create(
                client_id="partner",
                name="partner",
                client_secret="",
                client_type=OAuthApplication.CLIENT_PUBLIC,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="https://partner.example.com/callback",
                algorithm="RS256",
            )
            if with_application
            else None
        )

        def create() -> OrganizationProvisioning:
            return OrganizationProvisioning.objects.create(
                organization=self.organization, partner=partner, application=application
            )

        if allowed:
            assert create().partner == partner
        else:
            with transaction.atomic(), self.assertRaises(IntegrityError):
                create()
