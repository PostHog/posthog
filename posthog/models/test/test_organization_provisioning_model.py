from posthog.test.base import BaseTest

from django.db import transaction
from django.db.utils import IntegrityError

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

    @parameterized.expand(
        [
            ("billing_reports_a_payer", True),
            ("only_another_organization_of_the_partner_has_a_payer", False),
        ]
    )
    def test_billing_lock_on_an_organization_with_a_stripe_customer_follows_its_own_payer(
        self, _name: str, billing_has_payer: bool
    ) -> None:
        partner = OAuthApplication.objects.create(
            client_id="paying-partner",
            name="Paying Partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            is_provisioning_partner=True,
        )
        partner.update_provisioning(pays_for_customers=True)
        other_organization = Organization.objects.create(name="Other customer")
        for organization, has_payer in (
            (self.organization, billing_has_payer),
            (other_organization, not billing_has_payer),
        ):
            OrganizationProvisioning.objects.create(
                organization=organization,
                partner=OrganizationProvisioning.Partner.PROVISIONING_API,
                application=partner,
                billing_has_payer=has_payer,
            )
        self.organization.customer_id = "cus_example"

        assert get_billing_lock_partner(self.organization) == (partner if billing_has_payer else None)
