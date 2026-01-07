import re
from posthog.test.base import BaseTest

from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.organization import Organization, OrganizationMembership

from ee.models.rbac.access_control import AccessControl


class TestUser(BaseTest):
    def test_user_tracks_original_is_active_on_load(self):
        user = User.objects.create(email="tracker@example.com", is_active=True)

        # Reload from DB to trigger from_db
        loaded_user = User.objects.get(pk=user.pk)

        # Should have _original_is_active set to current value
        assert loaded_user._original_is_active
        assert loaded_user.is_active

        # Change is_active and verify _original_is_active still reflects original
        loaded_user.is_active = False
        assert loaded_user._original_is_active  # Still True (original)
        assert not loaded_user.is_active  # Now False (changed)

    def test_user_refresh_from_db_updates_original_is_active(self):
        user = User.objects.create(email="refresh@example.com", is_active=True)
        loaded_user = User.objects.get(pk=user.pk)

        # Simulate external change
        User.objects.filter(pk=user.pk).update(is_active=False)

        # Before refresh, _original_is_active is still True
        assert loaded_user._original_is_active

        # After refresh, _original_is_active should update
        loaded_user.refresh_from_db()
        assert not loaded_user._original_is_active
        assert not loaded_user.is_active

    def test_new_user_instance_has_no_original_is_active(self):
        # Newly constructed instances (not from DB) won't have _original_is_active
        new_user = User(email="new@example.com", is_active=True)
        assert not hasattr(new_user, "_original_is_active")

    def test_create_user_with_distinct_id(self):
        with self.settings(TEST=False):
            user = User.objects.create_user(first_name="Tim", email="tim@gmail.com", password=None)
        assert user.distinct_id != ""
        assert user.distinct_id is not None

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
            assert user.get_analytics_metadata() == {"realm": "cloud", "anonymize_data": True, "email": None, "is_signed_up": True, "organization_count": 1, "project_count": 1, "team_member_count_all": 1, "completed_onboarding_once": False, "organization_id": str(organization.id), "current_organization_membership_level": 15, "project_id": str(team.uuid), "project_setup_complete": False, "has_password_set": True, "joined_at": user.date_joined, "has_social_auth": False, "social_providers": [], "strapi_id": None, "instance_url": "http://localhost:8010", "instance_tag": "none", "is_email_verified": None, "has_seen_product_intro_for": None}

        # Multiple teams, multiple members, completed onboarding
        self.team.completed_snippet_onboarding = True
        self.team.ingested_event = True
        self.team.save()
        Team.objects.create(organization=self.organization)
        user_2: User = User.objects.create(email="test_org_2@posthog.com")
        user_2.join(organization=self.organization)

        with self.is_cloud(False):
            assert user_2.get_analytics_metadata() == {"realm": "hosted-clickhouse", "anonymize_data": False, "email": "test_org_2@posthog.com", "is_signed_up": True, "organization_count": 1, "project_count": 2, "team_member_count_all": 2, "completed_onboarding_once": True, "organization_id": str(self.organization.id), "current_organization_membership_level": 1, "project_id": str(self.team.uuid), "project_setup_complete": True, "has_password_set": True, "joined_at": user_2.date_joined, "has_social_auth": False, "social_providers": [], "strapi_id": None, "instance_url": "http://localhost:8010", "instance_tag": "none", "is_email_verified": None, "has_seen_product_intro_for": None}

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
        assert user.current_team == t2

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
        assert user.current_team == t1
