from django.db import IntegrityError
from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.organization_resource_access import OrganizationResourceAccess
from posthog.models.organization import Organization, OrganizationMembership
from posthog.test.base import QueryMatchingTest, snapshot_postgres_queries, FuzzyInt


class TestOrganizationResourceAccessAPI(APILicensedTest, QueryMatchingTest):
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
        self.assertEqual(
            get_res.json()["results"][0]["resource"],
            OrganizationResourceAccess.Resources.FEATURE_FLAGS,
        )

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
        other_org = Organization.objects.create(name="other org")
        OrganizationResourceAccess.objects.create(
            resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            organization=other_org,
        )
        self.assertEqual(OrganizationResourceAccess.objects.count(), 3)
        self.assertEqual(
            OrganizationResourceAccess.objects.filter(organization=other_org).exists(),
            True,
        )
        with self.assertRaises(IntegrityError):
            OrganizationResourceAccess.objects.create(
                resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
                organization=self.organization,
            )

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

        self.assertEqual(
            get_res.json()["access_level"],
            OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT,
        )

        change_access_level = self.client.patch(
            f"/api/organizations/@current/resource_access/{resource_id}",
            {"access_level": OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW},
        )
        self.assertEqual(change_access_level.status_code, status.HTTP_200_OK)

        get_updated_res = self.client.get(f"/api/organizations/@current/resource_access/{resource_id}")
        self.assertEqual(
            get_updated_res.json()["access_level"],
            OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW,
        )

    def test_default_edit_access_level_for_non_existing_resources(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.assertEqual(
            OrganizationResourceAccess.objects.filter(
                resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS
            ).exists(),
            False,
        )

        self.assertEqual(self.user.role_memberships.count(), 0)
        create_flag = self.client.post(
            "/api/projects/@current/feature_flags",
            {
                "name": "keropi",
                "key": "keropi",
            },
        )
        self.assertEqual(create_flag.status_code, status.HTTP_201_CREATED)
        flag_id = create_flag.json()["id"]
        get_res = self.client.get(f"/api/projects/@current/feature_flags/{flag_id}")
        self.assertEqual(get_res.json()["name"], "keropi")

    def test_returns_correct_results_by_organization(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.client.post(
            "/api/organizations/@current/resource_access",
            {
                "resource": OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            },
        )
        self.client.post(
            "/api/organizations/@current/resource_access",
            {
                "resource": OrganizationResourceAccess.Resources.COHORTS,
            },
        )
        other_org = Organization.objects.create(name="other org")
        OrganizationResourceAccess.objects.create(
            resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            organization=other_org,
        )
        self.assertEqual(OrganizationResourceAccess.objects.count(), 3)
        res = self.client.get("/api/organizations/@current/resource_access")
        results = res.json()
        self.assertEqual(results["count"], 2)
        self.assertNotContains(res, str(other_org.id))

    @snapshot_postgres_queries
    def test_list_organization_resource_access_is_not_nplus1(self):
        OrganizationResourceAccess.objects.create(
            resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            organization=self.organization,
        )

        with self.assertNumQueries(9):
            response = self.client.get("/api/organizations/@current/resource_access")
            assert len(response.json()["results"]) == 1

        OrganizationResourceAccess.objects.create(
            resource=OrganizationResourceAccess.Resources.EXPERIMENTS,
            organization=self.organization,
        )

        # one query less because rate limit instance setting was cached on last API call... maybe? sometimes?
        with self.assertNumQueries(FuzzyInt(8, 9)):
            response = self.client.get("/api/organizations/@current/resource_access")
            assert len(response.json()["results"]) == 2
