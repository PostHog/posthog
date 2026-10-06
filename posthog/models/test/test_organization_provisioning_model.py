from posthog.test.base import BaseTest

from django.db import transaction
from django.db.utils import IntegrityError

from parameterized import parameterized

from posthog.models.oauth import OAuthApplication
from posthog.models.organization_provisioning import OrganizationProvisioning


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
