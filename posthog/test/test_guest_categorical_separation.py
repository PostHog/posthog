from posthog.test.base import APIBaseTest

from posthog.models import OrganizationMembership, User


class TestGuestCategoricalSeparation(APIBaseTest):
    def setUp(self):
        super().setUp()
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self.regular_user = User.objects.create_user(email="r@x.com", password="x", first_name="R")
        OrganizationMembership.objects.create(organization=self.organization, user=self.regular_user, is_guest=False)
        self.guest_user = User.objects.create_user(email="g@x.com", password="x", first_name="G")
        OrganizationMembership.objects.create(organization=self.organization, user=self.guest_user, is_guest=True)

    def test_default_members_list_excludes_guests(self):
        response = self.client.get("/api/organizations/@current/members/")
        self.assertEqual(response.status_code, 200)
        emails = {m["user"]["email"] for m in response.json()["results"]}
        self.assertIn("r@x.com", emails)
        self.assertNotIn("g@x.com", emails)

    def test_is_guest_true_filter_returns_only_guests(self):
        response = self.client.get("/api/organizations/@current/members/?is_guest=true")
        self.assertEqual(response.status_code, 200)
        emails = {m["user"]["email"] for m in response.json()["results"]}
        self.assertEqual(emails, {"g@x.com"})

    def test_assignee_search_excludes_guests(self):
        response = self.client.get("/api/organizations/@current/members/?search=g")
        emails = {m["user"]["email"] for m in response.json().get("results", [])}
        self.assertNotIn("g@x.com", emails)
