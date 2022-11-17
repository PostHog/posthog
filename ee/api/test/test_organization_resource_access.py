from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.organization_resource_access import OrganizationResourceAccess
from posthog.models.organization import OrganizationMembership


class TestOrganizationResourceAccessAPI(APILicensedTest):
    def setUp(self):
        super().setUp()

    def test_only_organization_admins_and_higher_can_set_resource_access(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        admin_create_res = self.client.post(
            "/api/organizations/@current/resource_access",
            {
                "resource": OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            },
        )
        self.assertEqual(admin_create_res.status_code, status.HTTP_201_CREATED)
        get_res = self.client.get("/api/organizations/@current/resource_access")
        self.assertEqual(get_res.json()["count"], 1)
        self.assertEqual(get_res.json()["results"][0]["resource"], OrganizationResourceAccess.Resources.FEATURE_FLAGS)

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        member_create_res = self.client.post(
            "/api/organizations/@current/resource_access",
            {
                "resource": OrganizationResourceAccess.Resources.EXPERIMENTS,
            },
        )
        self.assertEqual(member_create_res.status_code, status.HTTP_403_FORBIDDEN)

    def test_can_only_create_one_instance_of_each_resource_type(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        create_ff_resource_access = self.client.post(
            "/api/organizations/@current/resource_access",
            {
                "resource": OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            },
        )

        self.assertEqual(create_ff_resource_access.status_code, status.HTTP_201_CREATED)

        create_ff_resource_access_again = self.client.post(
            "/api/organizations/@current/resource_access",
            {
                "resource": OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            },
        )
        self.assertEqual(create_ff_resource_access_again.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            create_ff_resource_access_again.json(),
            {
                "type": "validation_error",
                "code": "unique",
                "detail": "This resource access already exists.",
                "attr": "resource",
            },
        )

        create_exp_resource_access = self.client.post(
            "/api/organizations/@current/resource_access",
            {
                "resource": OrganizationResourceAccess.Resources.EXPERIMENTS,
            },
        )
        self.assertEqual(create_exp_resource_access.status_code, status.HTTP_201_CREATED)

    def test_can_change_access_levels_for_resources(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        create_res = self.client.post(
            "/api/organizations/@current/resource_access",
            {
                "resource": OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            },
        )
        resource_id = create_res.json()["id"]
        get_res = self.client.get(f"/api/organizations/@current/resource_access/{resource_id}")

        self.assertEqual(get_res.json()["access_level"], OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT)

        change_access_level = self.client.patch(
            f"/api/organizations/@current/resource_access/{resource_id}",
            {"access_level": OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW},
        )
        self.assertEqual(change_access_level.status_code, status.HTTP_200_OK)

        get_updated_res = self.client.get(f"/api/organizations/@current/resource_access/{resource_id}")
        self.assertEqual(get_updated_res.json()["access_level"], OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW)
