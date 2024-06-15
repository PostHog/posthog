from posthog.models import Team, User
from posthog.test.base import BaseTest


class TestUser(BaseTest):
    def test_create_user_with_distinct_id(self):
        with self.settings(TEST=False):
            user = User.objects.create_user(first_name="Tim", email="tim@gmail.com", password=None)
        self.assertNotEqual(user.distinct_id, "")
        self.assertNotEqual(user.distinct_id, None)

    def test_analytics_metadata(self):
        self.maxDiff = None
        # One org, one team, anonymized
        organization, team, user = User.objects.bootstrap(
            organization_name="Test Org",
            email="test_org@posthog.com",
            password="12345678",
            anonymize_data=True,
        )

        with self.is_cloud(True):
            self.assertEqual(
                user.get_analytics_metadata(),
                {
                    "realm": "cloud",
                    "anonymize_data": True,
                    "email": None,
                    "is_signed_up": True,
                    "organization_count": 1,
                    "project_count": 1,
                    "team_member_count_all": 1,
                    "completed_onboarding_once": False,
                    "organization_id": str(organization.id),
                    "current_organization_membership_level": 15,
                    "project_id": str(team.uuid),
                    "project_setup_complete": False,
                    "has_password_set": True,
                    "joined_at": user.date_joined,
                    "has_social_auth": False,
                    "social_providers": [],
                    "strapi_id": None,
                    "instance_url": "http://localhost:8000",
                    "instance_tag": "none",
                    "is_email_verified": None,
                    "has_seen_product_intro_for": None,
                },
            )

        # Multiple teams, multiple members, completed onboarding
        self.team.completed_snippet_onboarding = True
        self.team.ingested_event = True
        self.team.save()
        Team.objects.create(organization=self.organization)
        user_2: User = User.objects.create(email="test_org_2@posthog.com")
        user_2.join(organization=self.organization)

        with self.is_cloud(False):
            self.assertEqual(
                user_2.get_analytics_metadata(),
                {
                    "realm": "hosted-clickhouse",
                    "anonymize_data": False,
                    "email": "test_org_2@posthog.com",
                    "is_signed_up": True,
                    "organization_count": 1,
                    "project_count": 2,
                    "team_member_count_all": 2,
                    "completed_onboarding_once": True,
                    "organization_id": str(self.organization.id),
                    "current_organization_membership_level": 1,
                    "project_id": str(self.team.uuid),
                    "project_setup_complete": True,
                    "has_password_set": True,
                    "joined_at": user_2.date_joined,
                    "has_social_auth": False,
                    "social_providers": [],
                    "strapi_id": None,
                    "instance_url": "http://localhost:8000",
                    "instance_tag": "none",
                    "is_email_verified": None,
                    "has_seen_product_intro_for": None,
                },
            )
