from unittest.mock import Mock, patch

from dateutil.relativedelta import relativedelta
from django.test import tag
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.models import OrganizationMembership, Team, User
from posthog.test.base import BaseTest


class TestUser(BaseTest):
    @tag("ee")
    @patch("posthog.models.organization.License.PLANS", {"enterprise": ["whatever"]})
    @patch("ee.models.license.requests.post")
    def test_feature_available_self_hosted_has_license(self, patch_post):
        with self.settings(MULTI_TENANCY=False):
            from ee.models.license import License

            mock = Mock()
            mock.json.return_value = {"plan": "enterprise", "valid_until": now() + relativedelta(days=1)}
            patch_post.return_value = mock
            License.objects.create(key="key")
            self.assertTrue(self.organization.is_feature_available("whatever"))
            self.assertFalse(self.organization.is_feature_available("feature-doesnt-exist"))

    @tag("ee")
    @patch("posthog.models.organization.License.PLANS", {"enterprise": ["whatever"]})
    def test_feature_available_self_hosted_no_license(self):
        self.assertFalse(self.organization.is_feature_available("whatever"))
        self.assertFalse(self.organization.is_feature_available("feature-doesnt-exist"))

    @tag("ee")
    @patch("posthog.models.organization.License.PLANS", {"enterprise": ["whatever"]})
    @patch("ee.models.license.requests.post")
    def test_feature_available_self_hosted_license_expired(self, patch_post):
        from ee.models.license import License

        mock = Mock()
        mock.json.return_value = {"plan": "enterprise", "valid_until": "2012-01-14T12:00:00.000Z"}
        patch_post.return_value = mock
        License.objects.create(key="key")

        with freeze_time("2012-01-19T12:00:00.000Z"):
            self.assertFalse(self.organization.is_feature_available("whatever"))

    def test_create_user_with_distinct_id(self):
        with self.settings(TEST=False):
            user = User.objects.create_user(first_name="Tim", email="tim@gmail.com", password=None)
        self.assertNotEqual(user.distinct_id, "")
        self.assertNotEqual(user.distinct_id, None)

    def test_analytics_metadata(self):

        # One org, one team, anonymized
        organization, team, user = User.objects.bootstrap(
            company_name="Test Org", email="test_org@posthog.com", password="12345678", anonymize_data=True,
        )

        with self.settings(EE_AVAILABLE=True, MULTI_TENANCY=True):
            self.assertEqual(
                user.get_analytics_metadata(),
                {
                    "realm": "cloud",
                    "is_ee_available": True,
                    "email_opt_in": False,
                    "anonymize_data": True,
                    "email": None,
                    "is_signed_up": True,
                    "organization_count": 1,
                    "project_count": 1,
                    "team_member_count_all": 1,
                    "completed_onboarding_once": False,
                    "billing_plan": None,
                    "organization_id": str(organization.id),
                    "project_id": str(team.uuid),
                    "project_setup_complete": False,
                },
            )

        # Multiple teams, multiple members, completed onboarding
        user = User.objects.create(email="test_org_2@posthog.com", email_opt_in=True)
        OrganizationMembership.objects.create(user=user, organization=self.organization)
        Team.objects.create(organization=self.organization)
        self.team.completed_snippet_onboarding = True
        self.team.ingested_event = True
        self.team.save()

        with self.settings(EE_AVAILABLE=False, MULTI_TENANCY=False):
            self.assertEqual(
                user.get_analytics_metadata(),
                {
                    "realm": "hosted",
                    "is_ee_available": False,
                    "email_opt_in": True,
                    "anonymize_data": False,
                    "email": "test_org_2@posthog.com",
                    "is_signed_up": True,
                    "organization_count": 1,
                    "project_count": 2,
                    "team_member_count_all": 2,
                    "completed_onboarding_once": True,
                    "billing_plan": None,
                    "organization_id": str(self.organization.id),
                    "project_id": str(self.team.uuid),
                    "project_setup_complete": True,
                },
            )
