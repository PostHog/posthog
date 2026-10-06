from posthog.test.base import BaseTest

from django.db import transaction
from django.db.utils import IntegrityError
from django.test import TestCase

from parameterized import parameterized

from posthog.models.oauth import OAuthApplication
from posthog.models.organization import Organization
from posthog.models.organization_provisioning import OrganizationProvisioning, get_billing_lock_partner


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
            ("provisioning_api", "provisioning_api", True, None, "new"),
            ("stripe_projects", "stripe_projects", True, None, "new"),
            ("non_paying_application", "provisioning_api", False, None, None),
            ("vercel", "vercel", False, None, None),
            ("legacy_attribution", None, False, None, "legacy"),
            ("self_billed", "provisioning_api", True, "cus_example", None),
        ]
    )
    def test_billing_uses_organization_attribution_before_legacy_attribution(
        self,
        _name: str,
        source: str | None,
        pays_for_customers: bool,
        customer_id: str | None,
        expected: str | None,
    ) -> None:
        legacy_application = OAuthApplication.objects.create(
            client_id="legacy-partner",
            name="Legacy partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://legacy.example.com/callback",
            algorithm="RS256",
            is_provisioning_partner=True,
        )
        legacy_application.update_provisioning(pays_for_customers=True)
        OrganizationProvisioning.objects.create(
            organization=self.organization,
            partner=OrganizationProvisioning.Partner.PROVISIONING_API,
            application=legacy_application,
        )
        self.application.update_provisioning(pays_for_customers=pays_for_customers)
        self.organization.provisioning_source = source
        self.organization.provisioning_application = (
            self.application if source in {"provisioning_api", "stripe_projects"} else None
        )
        self.organization.customer_id = customer_id
        self.organization.save(update_fields=["provisioning_source", "provisioning_application", "customer_id"])

        expected_application = {"new": self.application, "legacy": legacy_application, None: None}[expected]
        assert get_billing_lock_partner(self.organization) == expected_application
