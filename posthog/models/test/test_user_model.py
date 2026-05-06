from posthog.test.base import BaseTest

from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.organization import Organization, OrganizationMembership

from ee.models.rbac.access_control import AccessControl


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
                    "instance_url": "http://localhost:8010",
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
                    "instance_url": "http://localhost:8010",
                    "instance_tag": "none",
                    "is_email_verified": None,
                    "has_seen_product_intro_for": None,
                },
            )

    def test_join_with_new_access_control_sets_allowed_team(self):
        # Org WITH ADVANCED_PERMISSIONS
        org = Organization.objects.create(name="RBAC Org")
        org.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": "Advanced permissions"}
        ]
        org.save()

        t1 = Team.objects.create(organization=org, name="T1")
        t2 = Team.objects.create(organization=org, name="T2")

        # Block T1 by default using AccessControl
        AccessControl.objects.create(team=t1, resource="project", resource_id=str(t1.id), access_level="none")

        user = User.objects.create(email="rbac@example.com")
        user.join(organization=org, level=OrganizationMembership.Level.MEMBER)

        user.refresh_from_db()
        # RBAC should pick t2
        self.assertEqual(user.current_team, t2)

    def test_join_admin_prefers_first_project_even_with_rbac(self):
        # Admins bypass RBAC filtering
        org = Organization.objects.create(name="Admin Org")
        org.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": "Advanced permissions"}
        ]
        org.save()

        t1 = Team.objects.create(organization=org, name="T1")
        Team.objects.create(organization=org, name="T2")

        # RBAC: explicitly block T1
        AccessControl.objects.create(team=t1, resource="project", resource_id=str(t1.id), access_level="none")

        user = User.objects.create(email="admin@example.com")
        user.join(organization=org, level=OrganizationMembership.Level.ADMIN)

        # Admin should be set to the first team
        user.refresh_from_db()
        self.assertEqual(user.current_team, t1)

    def test_from_db_sets_original_is_active(self):
        user = User.objects.create(email="from_db@example.com", is_active=True)

        loaded = User.objects.get(pk=user.pk)

        self.assertTrue(loaded._original_is_active)
        self.assertEqual(loaded._original_is_active, loaded.is_active)

    def test_from_db_sets_original_is_active_for_inactive_user(self):
        user = User.objects.create(email="inactive@example.com", is_active=False)

        loaded = User.objects.get(pk=user.pk)

        self.assertFalse(loaded._original_is_active)
        self.assertEqual(loaded._original_is_active, loaded.is_active)

    def test_get_by_natural_key_exact_match(self):
        user = User.objects.create(email="alice@example.com")
        self.assertEqual(User.objects.get_by_natural_key("alice@example.com"), user)

    def test_get_by_natural_key_is_case_insensitive(self):
        user = User.objects.create(email="Alastair.Pharo@example.com")

        self.assertEqual(User.objects.get_by_natural_key("alastair.pharo@example.com"), user)
        self.assertEqual(User.objects.get_by_natural_key("ALASTAIR.PHARO@example.com"), user)
        self.assertEqual(User.objects.get_by_natural_key("Alastair.Pharo@example.com"), user)

    def test_get_by_natural_key_raises_does_not_exist_when_missing(self):
        with self.assertRaises(User.DoesNotExist):
            User.objects.get_by_natural_key("nobody@example.com")

    def test_get_by_natural_key_finds_inactive_user(self):
        # Active-state filtering is the responsibility of ModelBackend.user_can_authenticate, not
        # this lookup. Mirror Django's default get_by_natural_key, which doesn't filter by is_active.
        user = User.objects.create(email="inactive@example.com", is_active=False)
        self.assertEqual(User.objects.get_by_natural_key("inactive@example.com"), user)

    def test_get_by_natural_key_with_multiple_case_variants_picks_most_recent_login(self):
        import datetime

        older = User.objects.create(email="dup@example.com")
        older.last_login = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
        older.save(update_fields=["last_login"])

        newer = User.objects.create(email="Dup@example.com")
        newer.last_login = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
        newer.save(update_fields=["last_login"])

        # Exact match wins over case-insensitive fallback when a row matches the typed casing.
        self.assertEqual(User.objects.get_by_natural_key("dup@example.com"), older)
        self.assertEqual(User.objects.get_by_natural_key("Dup@example.com"), newer)

        # When the typed casing matches no row exactly, fallback picks the most recent login.
        self.assertEqual(User.objects.get_by_natural_key("DUP@example.com"), newer)
