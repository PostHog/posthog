from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.db import connection

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User
from posthog.models.identity_provider_config import IdentityProviderConfig
from posthog.models.organization_domain import OrganizationDomain

from ee.api.scim.auth import generate_scim_token
from ee.api.test.base import APILicensedTest
from ee.models.scim_provisioned_user import SCIMProvisionedUser

backfill_scim_provisioned_user_config = import_module(
    "ee.migrations.0058_backfill_scim_provisioned_user_config"
).backfill_scim_provisioned_user_config


class TestSCIMRecordsWrittenBeforeConfigs(APILicensedTest):
    # SCIM used to be addressed per domain, so provisioning records were keyed on the domain. Those
    # records have to keep resolving, or the IdP re-provisions people it has already provisioned.

    def setUp(self):
        super().setUp()
        features = self.organization.available_product_features or []
        features.append({"key": AvailableFeature.SCIM, "name": "SCIM"})
        self.organization.available_product_features = features
        self.organization.save()

        self.domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="example.com",
            verified_at="2024-01-01T00:00:00Z",
        )
        token = generate_scim_token()
        self.config = IdentityProviderConfig.objects.create(
            organization=self.organization, scim_enabled=True, scim_bearer_token=token.hashed
        )
        self.domain.identity_provider_config = self.config
        self.domain.save()
        self.config.refresh_from_db()

        self.provisioned = User.objects.create_user(
            email="already@example.com", password=None, first_name="Already", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=self.provisioned, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        self.legacy_record = self._provision_keyed_on_domain(self.provisioned, "already.okta.username", self.domain)
        backfill_scim_provisioned_user_config(apps, SimpleNamespace(connection=connection))

        # The IdP keeps calling the URL it was configured with, which is the domain's id.
        self.scim_url = f"/scim/v2/{self.domain.id}"
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.plain}")

    def _provision_keyed_on_domain(self, user: User, username: str, domain: OrganizationDomain) -> SCIMProvisionedUser:
        return SCIMProvisionedUser.objects.create(
            user=user,
            organization_domain=domain,
            identity_provider=SCIMProvisionedUser.IdentityProvider.OKTA,
            username=username,
            active=True,
        )

    def test_the_url_the_idp_was_configured_with_still_authenticates(self):
        assert self.config.scim_slug == str(self.domain.id)
        assert self.client.get(f"{self.scim_url}/Users").status_code == status.HTTP_200_OK

    def test_record_keeps_its_username(self):
        response = self.client.get(f"{self.scim_url}/Users/{self.provisioned.id}")
        assert response.json()["userName"] == "already.okta.username"

    def test_record_is_found_by_username_filter(self):
        response = self.client.get(f'{self.scim_url}/Users?filter=userName eq "already.okta.username"')
        assert [resource["id"] for resource in response.json()["Resources"]] == [str(self.provisioned.id)]

    def test_user_is_not_provisioned_a_second_time(self):
        response = self.client.post(
            f"{self.scim_url}/Users",
            data={
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                "userName": "already.okta.username",
                "emails": [{"value": "already@example.com", "primary": True}],
                "active": True,
            },
            content_type="application/scim+json",
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert SCIMProvisionedUser.objects.filter(user=self.provisioned).count() == 1

    def test_deprovisioning_reaches_the_record(self):
        response = self.client.patch(
            f"{self.scim_url}/Users/{self.provisioned.id}",
            data={
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [{"op": "replace", "path": "active", "value": False}],
            },
            content_type="application/scim+json",
        )
        assert response.status_code == status.HTTP_200_OK
        self.legacy_record.refresh_from_db()
        assert self.legacy_record.active is False
        assert not OrganizationMembership.objects.filter(user=self.provisioned, organization=self.organization).exists()

    def test_record_written_after_the_backfill_is_claimed_not_duplicated(self):
        # A pod still running the pre-config code writes domain-keyed records for the length of a
        # rolling deploy. The backfill has already run by then, so only the write path can adopt them.
        late = User.objects.create_user(
            email="late@example.com", password=None, first_name="Late", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=late, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        self._provision_keyed_on_domain(late, "late.okta", self.domain)

        response = self.client.post(
            f"{self.scim_url}/Users",
            data={
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                "userName": "late.okta",
                "emails": [{"value": "late@example.com", "primary": True}],
                "active": True,
            },
            content_type="application/scim+json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert SCIMProvisionedUser.objects.filter(user=late).count() == 1
        assert self.client.get(f"{self.scim_url}/Users/{late.id}").json()["userName"] == "late.okta"

    @parameterized.expand(
        [
            ("deactivate", {"op": "replace", "path": "active", "value": False}),
            ("reactivate", {"op": "add", "path": "active", "value": True}),
            ("rename", {"op": "replace", "path": "name.givenName", "value": "Renamed"}),
            ("change_email", {"op": "replace", "path": "emails", "value": [{"value": "moved@example.com"}]}),
        ]
    )
    def test_patch_preserves_the_stored_username(self, _name: str, operation: dict):
        # The active toggles write the username back from the record they can find. Reading the
        # wrong one replaces the IdP's immutable id with the user's email, and the IdP stops
        # matching the user it provisioned.
        response = self.client.patch(
            f"{self.scim_url}/Users/{self.provisioned.id}",
            data={"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": [operation]},
            content_type="application/scim+json",
        )

        assert response.status_code == status.HTTP_200_OK
        self.legacy_record.refresh_from_db()
        assert self.legacy_record.username == "already.okta.username"

    def test_patch_username_still_replaces_it(self):
        response = self.client.patch(
            f"{self.scim_url}/Users/{self.provisioned.id}",
            data={
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [{"op": "replace", "path": "userName", "value": "renamed.okta"}],
            },
            content_type="application/scim+json",
        )

        assert response.status_code == status.HTTP_200_OK
        self.legacy_record.refresh_from_db()
        assert self.legacy_record.username == "renamed.okta"

    def test_write_does_not_collide_with_a_record_the_backfill_skipped(self):
        # One user provisioned through two domains of one config keeps a second record on its domain
        # key. Claiming that one for the config would trip the (user, config) unique constraint.
        second_domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="partner.example.com",
            verified_at="2024-01-01T00:00:00Z",
            identity_provider_config=self.config,
        )
        skipped = self._provision_keyed_on_domain(self.provisioned, "already.partner.username", second_domain)

        response = self.client.patch(
            f"{self.scim_url}/Users/{self.provisioned.id}",
            data={
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [{"op": "replace", "path": "userName", "value": "renamed.okta"}],
            },
            content_type="application/scim+json",
        )

        assert response.status_code == status.HTTP_200_OK
        self.legacy_record.refresh_from_db()
        skipped.refresh_from_db()
        assert self.legacy_record.username == "renamed.okta"
        assert skipped.identity_provider_config_id is None
