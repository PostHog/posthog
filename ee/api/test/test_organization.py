import datetime as dt
from unittest import mock
from unittest.mock import ANY, call, patch

from freezegun.api import freeze_time
from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.license import License
from posthog.models import Team, User
from posthog.models.organization import Organization, OrganizationMembership
from posthog.tasks.tasks import sync_all_organization_available_product_features


class TestOrganizationEnterpriseAPI(APILicensedTest):
    def test_create_organization(self):
        response = self.client.post("/api/organizations/", {"name": "Test"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Organization.objects.count(), 2)
        response_data = response.json()
        self.assertEqual(response_data.get("name"), "Test")
        self.assertEqual(
            OrganizationMembership.objects.filter(organization_id=response_data.get("id")).count(),
            1,
        )
        self.assertEqual(
            OrganizationMembership.objects.get(organization_id=response_data.get("id"), user=self.user).level,
            OrganizationMembership.Level.OWNER,
        )

    @patch("posthog.models.utils.generate_random_short_suffix", return_value="YYYY")
    def test_create_two_similarly_named_organizations(self, mock_choice):
        response = self.client.post(
            "/api/organizations/",
            {"name": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertDictContainsSubset(
            {
                "name": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                "slug": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            },
            response.json(),
        )

        response = self.client.post(
            "/api/organizations/",
            {"name": "#XXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxX"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertDictContainsSubset(
            {
                "name": "#XXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxX",
                "slug": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx-YYYY",
            },
            response.json(),
        )

    @patch("posthog.api.organization.delete_bulky_postgres_data")
    @patch("posthoganalytics.capture")
    def test_delete_second_managed_organization(self, mock_capture, mock_delete_bulky_postgres_data):
        organization, _, team = Organization.objects.bootstrap(self.user, name="X")
        organization_props = organization.get_analytics_metadata()
        self.assertTrue(Organization.objects.filter(id=organization.id).exists())
        self.assertTrue(Team.objects.filter(id=team.id).exists())
        response = self.client.delete(f"/api/organizations/{organization.id}")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Organization.objects.filter(id=organization.id).exists())
        self.assertFalse(Team.objects.filter(id=team.id).exists())

        mock_capture.assert_called_once_with(
            self.user.distinct_id,
            "organization deleted",
            organization_props,
            groups={"instance": ANY, "organization": str(organization.id)},
        )
        mock_delete_bulky_postgres_data.assert_called_once_with(team_ids=[team.id])

    @patch("posthoganalytics.capture")
    def test_delete_last_organization(self, mock_capture):
        org_id = self.organization.id
        organization_props = self.organization.get_analytics_metadata()
        self.assertTrue(Organization.objects.filter(id=org_id).exists())

        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()

        response = self.client.delete(f"/api/organizations/{org_id}")

        self.assertEqual(
            response.status_code,
            204,
            "Did not successfully delete last organization on the instance",
        )
        self.assertFalse(Organization.objects.filter(id=org_id).exists())
        self.assertFalse(Organization.objects.exists())

        response_bis = self.client.delete(f"/api/organizations/{org_id}")

        self.assertEqual(
            response_bis.status_code,
            404,
            "Did not return a 404 on trying to delete a nonexistent org",
        )

        mock_capture.assert_has_calls(
            [
                call(
                    self.user.distinct_id,
                    "membership level changed",
                    properties={"new_level": 15, "previous_level": 1, "$set": mock.ANY},
                    groups=mock.ANY,
                ),
                call(
                    self.user.distinct_id,
                    "organization deleted",
                    organization_props,
                    groups={"instance": mock.ANY, "organization": str(org_id)},
                ),
            ]
        )

    def test_no_delete_organization_not_owning(self):
        for level in (
            OrganizationMembership.Level.MEMBER,
            OrganizationMembership.Level.ADMIN,
        ):
            self.organization_membership.level = level
            self.organization_membership.save()
            response = self.client.delete(f"/api/organizations/{self.organization.id}")
            potential_err_message = f"Somehow managed to delete the org as a level {level} (which is not owner)"
            self.assertEqual(
                response.json(),
                {
                    "attr": None,
                    "detail": "Your organization access level is insufficient.",
                    "code": "permission_denied",
                    "type": "authentication_error",
                },
                potential_err_message,
            )
            self.assertEqual(response.status_code, 403, potential_err_message)
            self.assertTrue(self.organization.name, self.CONFIG_ORGANIZATION_NAME)

    def test_delete_organization_owning(self):
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        membership_ids = OrganizationMembership.objects.filter(organization=self.organization).values_list(
            "id", flat=True
        )

        response = self.client.delete(f"/api/organizations/{self.organization.id}")

        potential_err_message = f"Somehow did not delete the org as the owner"
        self.assertEqual(response.status_code, 204, potential_err_message)
        self.assertFalse(
            Organization.objects.filter(id=self.organization.id).exists(),
            potential_err_message,
        )
        self.assertFalse(OrganizationMembership.objects.filter(id__in=membership_ids).exists())
        self.assertTrue(User.objects.filter(id=self.user.pk).exists())

    def test_no_delete_organization_not_belonging_to(self):
        for level in OrganizationMembership.Level:
            self.organization_membership.level = level
            self.organization_membership.save()
            organization = Organization.objects.create(name="Some Other Org")
            response = self.client.delete(f"/api/organizations/{organization.id}")
            potential_err_message = f"Somehow managed to delete someone else's org as a level {level} in own org"
            self.assertEqual(
                response.json(),
                {
                    "attr": None,
                    "detail": "Not found.",
                    "code": "not_found",
                    "type": "invalid_request",
                },
                potential_err_message,
            )
            self.assertEqual(response.status_code, 404, potential_err_message)
            self.assertTrue(
                Organization.objects.filter(id=organization.id).exists(),
                potential_err_message,
            )

    def test_update_org(self):
        for level in OrganizationMembership.Level:
            self.organization_membership.level = level
            self.organization_membership.save()
            response_rename = self.client.patch(f"/api/organizations/{self.organization.id}", {"name": "Woof"})
            response_email = self.client.patch(
                f"/api/organizations/{self.organization.id}",
                {"is_member_join_email_enabled": False},
            )
            self.organization.refresh_from_db()

            expected_response = {
                "attr": None,
                "detail": "Your organization access level is insufficient.",
                "code": "permission_denied",
                "type": "authentication_error",
            }
            if level < OrganizationMembership.Level.ADMIN:
                potential_err_message = f"Somehow managed to update the org as a level {level} (which is below admin)"
                self.assertEqual(response_rename.json(), expected_response, potential_err_message)
                self.assertEqual(response_rename.status_code, 403, potential_err_message)
                self.assertTrue(self.organization.name, self.CONFIG_ORGANIZATION_NAME)
                self.assertEqual(response_email.json(), expected_response, potential_err_message)
                self.assertEqual(response_email.status_code, 403, potential_err_message)
            else:
                potential_err_message = f"Somehow did not update the org as a level {level} (which is at least admin)"
                self.assertEqual(response_rename.status_code, 200, potential_err_message)
                self.assertEqual(response_email.status_code, 200, potential_err_message)
                self.assertTrue(self.organization.name, "Woof")

    def test_no_update_organization_not_belonging_to(self):
        for level in OrganizationMembership.Level:
            self.organization_membership.level = level
            self.organization_membership.save()
            organization = Organization.objects.create(name="Meow")
            response = self.client.patch(f"/api/organizations/{organization.id}", {"name": "Mooooooooo"})
            potential_err_message = f"Somehow managed to update someone else's org as a level {level} in own org"
            self.assertEqual(
                response.json(),
                {
                    "attr": None,
                    "detail": "Not found.",
                    "code": "not_found",
                    "type": "invalid_request",
                },
                potential_err_message,
            )
            self.assertEqual(response.status_code, 404, potential_err_message)
            organization.refresh_from_db()
            self.assertTrue(organization.name, "Meow")

    def test_feature_available_self_hosted_has_license(self):
        current_plans = License.PLANS
        License.PLANS = {"enterprise": ["whatever"]}  # type: ignore
        with self.is_cloud(False):
            License.objects.create(
                key="key",
                plan="enterprise",
                valid_until=dt.datetime.now() + dt.timedelta(days=1),
            )

            # Still only old, empty available_product_features field value known
            self.assertFalse(self.organization.is_feature_available("whatever"))
            self.assertFalse(self.organization.is_feature_available("feature-doesnt-exist"))

            # New available_product_features field value that was updated in DB on license creation is known after refresh
            self.organization.refresh_from_db()
            self.assertTrue(self.organization.is_feature_available("whatever"))
            self.assertFalse(self.organization.is_feature_available("feature-doesnt-exist"))
        License.PLANS = current_plans

    def test_feature_available_self_hosted_no_license(self):
        current_plans = License.PLANS
        License.PLANS = {"enterprise": ["whatever"]}  # type: ignore

        self.assertFalse(self.organization.is_feature_available("whatever"))
        self.assertFalse(self.organization.is_feature_available("feature-doesnt-exist"))
        License.PLANS = current_plans

    @patch("ee.api.license.requests.post")
    def test_feature_available_self_hosted_license_expired(self, patch_post):
        current_plans = License.PLANS
        License.PLANS = {"enterprise": ["whatever"]}  # type: ignore

        with freeze_time("2070-01-01T12:00:00.000Z"):  # LicensedTestMixin enterprise license expires in 2038
            sync_all_organization_available_product_features()  # This is normally ran every hour
            self.organization.refresh_from_db()
            self.assertFalse(self.organization.is_feature_available("whatever"))
        License.PLANS = current_plans

    def test_get_organization_restricted_teams_hidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        Team.objects.create(
            organization=self.organization,
            name="FORBIDDEN",
            access_control=True,
        )

        response = self.client.get(f"/api/organizations/{self.organization.id}")

        self.assertEqual(response.status_code, 200)
        self.assertListEqual(
            [team["name"] for team in response.json()["teams"]],
            [self.team.name],  # "FORBIDDEN" excluded
        )
