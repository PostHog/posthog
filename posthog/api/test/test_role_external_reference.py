from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.role_external_reference import RoleExternalReference

from ee.api.test.base import APILicensedTest
from ee.models.rbac.role import Role


class TestRoleExternalReferenceAPI(APILicensedTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.role = Role.objects.create(name="Frontend", organization=self.organization)

    def _base_url(self, org_id: str | None = None) -> str:
        selected_org_id = org_id or str(self.organization.id)
        return f"/api/organizations/{selected_org_id}/role_external_references"

    def _create_reference(self, **overrides: str):
        payload = {
            "provider": "github",
            "provider_organization_id": "posthog",
            "provider_role_id": "12345",
            "provider_role_slug": "frontend-team",
            "provider_role_name": "Frontend Team",
            "role": str(self.role.id),
            **overrides,
        }
        return self.client.post(f"{self._base_url()}/", payload)

    def test_create_list_delete(self) -> None:
        create_response = self._create_reference()
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        list_response = self.client.get(f"{self._base_url()}/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.json()["results"]), 1)

        reference_id = create_response.json()["id"]
        delete_response = self.client.delete(f"{self._base_url()}/{reference_id}/")
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(RoleExternalReference.objects.filter(id=reference_id).exists())

    @parameterized.expand(
        [
            ("provider_role_slug=frontend-team", "provider_role_slug", "frontend-team"),
            ("provider_role_id=12345", "provider_role_id", "12345"),
        ]
    )
    def test_lookup(self, query_string: str, expected_key: str, expected_value: str) -> None:
        self._create_reference()
        response = self.client.get(
            f"{self._base_url()}/lookup/?provider=github&provider_organization_id=posthog&{query_string}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.json()["reference"])
        self.assertEqual(response.json()["reference"][expected_key], expected_value)

    def test_lookup_requires_identifier(self) -> None:
        response = self.client.get(f"{self._base_url()}/lookup/?provider=github&provider_organization_id=posthog")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(
        [
            ({"provider_role_id": "67890"},),
            ({"provider_role_slug": "Frontend-Team", "provider_organization_id": "PostHog"},),
        ]
    )
    def test_unique_constraint_on_role_slug(self, overrides: dict[str, str]) -> None:
        self._create_reference()
        response = self._create_reference(**overrides)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unique_constraint_on_role_id(self) -> None:
        self._create_reference()
        response = self._create_reference(provider_role_slug="other-team")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestRoleExternalReferencePermissions(APILicensedTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.role = Role.objects.create(name="Frontend", organization=self.organization)

    def _base_url(self) -> str:
        return f"/api/organizations/{self.organization.id}/role_external_references"

    def test_member_can_list(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.get(f"{self._base_url()}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_member_cannot_create(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(
            f"{self._base_url()}/",
            {
                "provider": "github",
                "provider_organization_id": "posthog",
                "provider_role_id": "12345",
                "provider_role_slug": "frontend-team",
                "provider_role_name": "Frontend Team",
                "role": str(self.role.id),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestRoleExternalReferenceCrossOrgIsolation(APILicensedTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.org_a = self.organization
        self.role_a = Role.objects.create(name="Role A", organization=self.org_a)

        self.org_b = Organization.objects.create(name="Org B")
        self.org_b.update_available_product_features()
        self.org_b.save()
        self.role_b = Role.objects.create(name="Role B", organization=self.org_b)

        self.ref_a = RoleExternalReference.objects.create(
            organization=self.org_a,
            role=self.role_a,
            provider="github",
            provider_organization_id="posthog",
            provider_role_id="111",
            provider_role_slug="team-a",
            provider_role_name="Team A",
            created_by=self.user,
        )
        self.ref_b = RoleExternalReference.objects.create(
            organization=self.org_b,
            role=self.role_b,
            provider="github",
            provider_organization_id="posthog",
            provider_role_id="222",
            provider_role_slug="team-b",
            provider_role_name="Team B",
            created_by=self.user,
        )

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def test_list_only_returns_current_org_references(self) -> None:
        response = self.client.get(f"/api/organizations/{self.org_a.id}/role_external_references/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.ref_a.id))

    def test_cannot_delete_reference_from_other_org(self) -> None:
        response = self.client.delete(f"/api/organizations/{self.org_a.id}/role_external_references/{self.ref_b.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
