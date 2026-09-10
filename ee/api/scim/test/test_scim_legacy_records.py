from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User
from posthog.models.identity_provider_config import IdentityProviderConfig
from posthog.models.linked_identity_provider_config import LinkedIdentityProviderConfig
from posthog.models.organization_domain import OrganizationDomain

from ee.api.scim.auth import generate_scim_token
from ee.api.test.base import APILicensedTest
from ee.models.scim_provisioned_user import SCIMProvisionedUser


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
        LinkedIdentityProviderConfig.objects.create(
            organization_domain=self.domain, identity_provider_config=self.config
        )
        self.config.refresh_from_db()

        self.provisioned = User.objects.create_user(
            email="already@example.com", password=None, first_name="Already", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=self.provisioned, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        self.legacy_record = self._provision_keyed_on_domain(self.provisioned, "already.okta.username", self.domain)
        SCIMProvisionedUser.objects.filter(pk=self.legacy_record.pk).update(identity_provider_config=self.config)

        assert self.config.scim_slug != self.domain.id
        self.scim_url = f"/scim/v2/{self.config.scim_slug}"
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.plain}")

    def _provision_keyed_on_domain(self, user: User, username: str, domain: OrganizationDomain) -> SCIMProvisionedUser:
        return SCIMProvisionedUser.objects.create(
            user=user,
            organization_domain=domain,
            identity_provider=SCIMProvisionedUser.IdentityProvider.OKTA,
            username=username,
            active=True,
        )

    def test_the_config_url_authenticates(self):
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

    def test_another_configs_records_are_out_of_scope(self):
        # An organization can run several IdPs, each with its own config. Once a record belongs to
        # one of them, moving the domain under another must not hand over the users: a config that
        # never provisioned someone can neither read the id its IdP knows them by nor deprovision
        # them. The domain-keyed fallback only ever covers records no config has claimed.
        second_token = generate_scim_token()
        second_config = IdentityProviderConfig.objects.create(
            organization=self.organization,
            scim_enabled=True,
            scim_bearer_token=second_token.hashed,
        )
        LinkedIdentityProviderConfig.objects.filter(organization_domain=self.domain).delete()
        LinkedIdentityProviderConfig.objects.create(
            organization_domain=self.domain, identity_provider_config=second_config
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {second_token.plain}")

        read = self.client.get(f"/scim/v2/{second_config.scim_slug}/Users/{self.provisioned.id}")
        deprovision = self.client.delete(f"/scim/v2/{second_config.scim_slug}/Users/{self.provisioned.id}")

        assert read.json()["userName"] == "already@example.com"  # its own view of the user, not the other config's
        assert deprovision.status_code == status.HTTP_204_NO_CONTENT
        assert SCIMProvisionedUser.objects.filter(pk=self.legacy_record.pk).exists()

    def test_claiming_a_second_unclaimed_record_does_not_surface_the_constraint(self):
        # Two domains of one config can each hold an unclaimed record for the same user. Claiming
        # one takes (user, config), so the next write's attempt on the other hits the unique
        # constraint — concurrently on a rolling deploy, or in sequence as here. It has to converge
        # on the winner rather than surfacing an IntegrityError as a 500 to the IdP.
        second_domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="partner.example.com",
            verified_at="2024-01-01T00:00:00Z",
        )
        LinkedIdentityProviderConfig.objects.create(
            organization_domain=second_domain, identity_provider_config=self.config
        )
        sibling = self._provision_keyed_on_domain(self.provisioned, "already.partner.username", second_domain)
        SCIMProvisionedUser.objects.filter(pk=self.legacy_record.pk).update(identity_provider_config=self.config)

        for username in ("first.write", "second.write"):
            response = self.client.patch(
                f"{self.scim_url}/Users/{self.provisioned.id}",
                data={
                    "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                    "Operations": [{"op": "replace", "path": "userName", "value": username}],
                },
                content_type="application/scim+json",
            )
            assert response.status_code == status.HTTP_200_OK, response.json()

        self.legacy_record.refresh_from_db()
        sibling.refresh_from_db()
        assert self.legacy_record.username == "second.write"
        assert sibling.identity_provider_config_id is None
        assert (
            SCIMProvisionedUser.objects.filter(user=self.provisioned, identity_provider_config=self.config).count() == 1
        )

    def test_write_does_not_collide_with_a_record_the_backfill_skipped(self):
        # One user provisioned through two domains of one config keeps a second record on its domain
        # key. Claiming that one for the config would trip the (user, config) unique constraint.
        second_domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="partner.example.com",
            verified_at="2024-01-01T00:00:00Z",
        )
        LinkedIdentityProviderConfig.objects.create(
            organization_domain=second_domain, identity_provider_config=self.config
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
