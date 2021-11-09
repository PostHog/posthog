from posthog.models import OrganizationMembership, Team, User
from posthog.test.base import BaseTest


class TestUser(BaseTest):
    def test_create_user_with_distinct_id(self):
        with self.settings(TEST=False):
            user = User.objects.create_user(first_name="Tim", email="tim@gmail.com", password=None)
        self.assertNotEqual(user.distinct_id, "")
        self.assertNotEqual(user.distinct_id, None)

    def test_analytics_metadata(self):
        # One org, one team, anonymized
        organization, team, user = User.objects.bootstrap(
            organization_name="Test Org", email="test_org@posthog.com", password="12345678", anonymize_data=True,
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
                    "has_password_set": True,
                    "joined_at": user.date_joined,
                    "has_social_auth": False,
                    "social_providers": [],
                },
            )

        # Multiple teams, multiple members, completed onboarding
        self.team.completed_snippet_onboarding = True
        self.team.ingested_event = True
        self.team.save()
        team_2: Team = Team.objects.create(organization=self.organization)
        user_2: User = User.objects.create(email="test_org_2@posthog.com", email_opt_in=True)
        user_2.join(organization=self.organization)

        with self.settings(EE_AVAILABLE=False, MULTI_TENANCY=False):
            self.assertEqual(
                user_2.get_analytics_metadata(),
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
                    "has_password_set": True,
                    "joined_at": user_2.date_joined,
                    "has_social_auth": False,
                    "social_providers": [],
                },
            )
