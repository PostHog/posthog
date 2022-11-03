from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.role import Role
from posthog.models.organization import OrganizationMembership


class TestRoleMembershipAPI(APILicensedTest):
    def setUp(self):
        super().setUp()
        self.eng_role = Role.objects.create(name="Engineering")
        self.marketing_role = Role.objects.create(name="Marketing")

    # self.test_role = Role.objects.create(name="Marketing", created_by=self.user)
