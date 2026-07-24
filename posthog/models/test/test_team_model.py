from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import connection, models

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.core_event import CoreEvent
from posthog.models.organization import OrganizationMembership
from posthog.models.project import Project
from posthog.models.team.team import Team
from posthog.models.team.team_caching import get_team_in_cache, set_team_in_cache
from posthog.models.user import User

from ee.models.explicit_team_membership import ExplicitTeamMembership
from ee.models.rbac.access_control import AccessControl
from ee.models.rbac.role import Role, RoleMembership


class TestCoreEvent(BaseTest):
    @parameterized.expand(
        [
            (
                "event goal",
                "Purchase",
                "monetization",
                {"kind": "EventsNode", "event": "$purchase"},
            ),
            (
                "action goal",
                "Signup Action",
                "activation",
                {"kind": "ActionsNode", "id": 123},
            ),
            (
                "data warehouse goal",
                "Stripe Charges",
                "monetization",
                {
                    "kind": "DataWarehouseNode",
                    "id": "stripe_charges",
                    "table_name": "stripe_charges",
                    "timestamp_field": "created_at",
                    "distinct_id_field": "customer_email",
                    "id_field": "id",
                },
            ),
            (
                "event goal with math sum",
                "Revenue",
                "monetization",
                {
                    "kind": "EventsNode",
                    "event": "purchase",
                    "math": "sum",
                    "math_property": "revenue",
                },
            ),
        ]
    )
    def test_core_events_valid(self, _name: str, name: str, category: str, filter: dict):
        core_event = CoreEvent.objects.create(
            team=self.team,
            name=name,
            category=category,
            filter=filter,
        )
        core_event.refresh_from_db()

        assert core_event.name == name
        assert core_event.category == category
        assert core_event.filter == filter

    def test_core_events_empty_by_default(self):
        assert self.team.core_events.count() == 0

    def test_core_events_missing_filter_raises(self):
        with self.assertRaises(ValidationError):
            CoreEvent.objects.create(
                team=self.team,
                name="Bad Goal",
                category="monetization",
                filter=None,
            )

    def test_core_events_invalid_filter_kind_raises(self):
        with self.assertRaises(ValidationError):
            CoreEvent.objects.create(
                team=self.team,
                name="Bad Goal",
                category="monetization",
                filter={"kind": "InvalidNode"},
            )

    def test_core_events_all_events_not_allowed(self):
        """All events (empty event name) should not be allowed as a core event."""
        with self.assertRaises(ValidationError) as context:
            CoreEvent.objects.create(
                team=self.team,
                name="All Events Goal",
                category="monetization",
                filter={"kind": "EventsNode", "event": None},
            )
        assert "All events" in str(context.exception)

    def test_core_events_empty_event_name_not_allowed(self):
        """Empty event name should not be allowed as a core event."""
        with self.assertRaises(ValidationError) as context:
            CoreEvent.objects.create(
                team=self.team,
                name="Empty Event Goal",
                category="monetization",
                filter={"kind": "EventsNode", "event": ""},
            )
        assert "All events" in str(context.exception)


class TestTeam(BaseTest):
    def _enable_access_control(self, role_based: bool = False) -> None:
        from posthog.constants import AvailableFeature

        features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}]
        if role_based:
            features.append({"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS})
        self.organization.available_product_features = features
        self.organization.save()

    def test_all_users_with_access_simple_org_membership(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        another_user = User.objects.create_and_join(self.organization, "test2@posthog.com", None)

        all_user_with_access_ids = list(self.team.all_users_with_access().values_list("id", flat=True))

        assert sorted(all_user_with_access_ids) == sorted([self.user.id, another_user.id])

    def test_all_users_with_access_simple_org_membership_and_redundant_team_one(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        another_user = User.objects.create_and_join(self.organization, "test2@posthog.com", None)
        ExplicitTeamMembership.objects.create(team=self.team, parent_membership=self.organization_membership)

        all_user_with_access_ids = list(self.team.all_users_with_access().values_list("id", flat=True))

        assert sorted(all_user_with_access_ids) == sorted(
            [self.user.id, another_user.id]
        )  # self.user should only be listed once

    def test_all_users_with_access_new_access_control_non_private_team(self):
        """Test that all organization members have access to a non-private team with the new access control system"""

        # Create another user as a member
        member_user = User.objects.create_and_join(
            self.organization,
            email="member@posthog.com",
            first_name="first_name",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )

        # Get all users with access
        all_user_with_access_ids = list(self.team.all_users_with_access().values_list("id", flat=True))

        # Both users should have access since the team is not private
        assert sorted(all_user_with_access_ids) == sorted([self.user.id, member_user.id])

    def test_all_users_with_access_new_access_control_private_team(self):
        """Test that only users with specific access have access to a private team with the new access control system"""
        self._enable_access_control()

        # Make the team private
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        # Create another user as a member
        User.objects.create_and_join(
            self.organization,
            email="member@posthog.com",
            first_name="first_name",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )

        # Set the original user as admin
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Get all users with access
        all_user_with_access_ids = list(self.team.all_users_with_access().values_list("id", flat=True))

        # Only the admin user should have access
        assert all_user_with_access_ids == [self.user.id]

    def test_all_users_with_access_new_access_control_private_team_with_member_access(self):
        """Test that users with specific member access have access to a private team with the new access control system"""
        self._enable_access_control()

        # Make the team private
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        # Create another user as a member
        member_user = User.objects.create_and_join(
            self.organization,
            email="member@posthog.com",
            first_name="first_name",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )
        member_org_membership = OrganizationMembership.objects.get(organization=self.organization, user=member_user)

        # Give the member user access to the team
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=member_org_membership,
            access_level="member",
        )

        # Set the original user as admin
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Get all users with access
        all_user_with_access_ids = list(self.team.all_users_with_access().values_list("id", flat=True))

        # Both users should have access
        assert sorted(all_user_with_access_ids) == sorted([self.user.id, member_user.id])

    def test_all_users_with_access_new_access_control_private_team_with_role_access(self):
        """Test that users with role-based access have access to a private team with the new access control system"""
        self._enable_access_control(role_based=True)

        # Make the team private
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        # Create another user as a member
        member_user = User.objects.create_and_join(
            self.organization,
            email="member@posthog.com",
            first_name="first_name",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )
        member_org_membership = OrganizationMembership.objects.get(organization=self.organization, user=member_user)

        # Create a role
        role = Role.objects.create(name="Test Role", organization=self.organization)

        # Assign the member to the role
        RoleMembership.objects.create(role=role, user=member_user, organization_member=member_org_membership)

        # Give the role access to the team
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), role=role, access_level="member"
        )

        # Set the original user as admin
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Get all users with access
        all_user_with_access_ids = list(self.team.all_users_with_access().values_list("id", flat=True))

        # Both users should have access
        assert sorted(all_user_with_access_ids) == sorted([self.user.id, member_user.id])

    def test_all_users_with_access_returns_all_org_members_without_access_control_feature(self):
        """Without ACCESS_CONTROL there are no private teams — every org member has access,
        even if AccessControl rows exist in the DB."""
        # No features enabled
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )
        member_user = User.objects.create_and_join(
            self.organization,
            email="member-no-feature@posthog.com",
            first_name="first_name",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )

        all_user_with_access_ids = list(self.team.all_users_with_access().values_list("id", flat=True))
        # Both users in, despite the private AccessControl row
        assert sorted(all_user_with_access_ids) == sorted([self.user.id, member_user.id])

    def test_all_users_with_access_role_access_inert_without_role_based_access_feature(self):
        """With ACCESS_CONTROL but no ROLE_BASED_ACCESS, role-backed AccessControl rows
        must not grant access — mirrors the UI gate and User.teams behaviour."""
        self._enable_access_control()  # ACCESS_CONTROL only

        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )
        member_user = User.objects.create_and_join(
            self.organization,
            email="member-no-rbac@posthog.com",
            first_name="first_name",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )
        member_org_membership = OrganizationMembership.objects.get(organization=self.organization, user=member_user)
        role = Role.objects.create(name="Test Role", organization=self.organization)
        RoleMembership.objects.create(role=role, user=member_user, organization_member=member_org_membership)
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), role=role, access_level="member"
        )

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        all_user_with_access_ids = list(self.team.all_users_with_access().values_list("id", flat=True))
        # Only the org admin gets access — the role-backed member does not
        assert all_user_with_access_ids == [self.user.id]


class TestTeamSetTokenAndSave(BaseTest):
    _api_token_field = Team._meta.get_field("api_token")
    assert isinstance(_api_token_field, models.CharField)
    assert _api_token_field.max_length is not None, "api_token CharField must declare a max_length"
    API_TOKEN_MAX_LENGTH: int = _api_token_field.max_length

    def setUp(self) -> None:
        super().setUp()
        self.team.api_token = "phc_old_token_value"
        self.team.save()

    @parameterized.expand(
        [
            ("empty", "", "non-empty"),
            ("whitespace_only", "   ", "non-empty"),
            ("too_long", "a" * (API_TOKEN_MAX_LENGTH + 1), f"{API_TOKEN_MAX_LENGTH} characters"),
            ("identical", "phc_old_token_value", "identical"),
        ]
    )
    def test_set_token_and_save_validation_rejects_invalid(self, _name: str, new_token: str, message_fragment: str):
        with self.assertRaises(ValueError) as ctx:
            self.team.set_token_and_save(
                new_token=new_token,
                user=self.user,
                is_impersonated_session=False,
            )
        assert message_fragment in str(ctx.exception)
        self.team.refresh_from_db()
        assert self.team.api_token == "phc_old_token_value"

    @patch("posthog.tasks.integrations.push_vercel_secrets.delay")
    @patch("posthog.models.team.team.set_team_in_cache")
    def test_set_token_and_save_success_runs_full_side_effect_chain(self, mock_set_cache, mock_push_vercel) -> None:
        self.team.set_token_and_save(
            new_token="phc_new_token_value",
            user=self.user,
            is_impersonated_session=False,
        )

        self.team.refresh_from_db()
        assert self.team.api_token == "phc_new_token_value"

        cache_calls = [call.args for call in mock_set_cache.call_args_list]
        assert ("phc_old_token_value", None) in cache_calls
        assert any(args[0] == "phc_new_token_value" and args[1] is self.team for args in cache_calls)

        mock_push_vercel.assert_called_once_with(self.team.id)

        log_entry = ActivityLog.objects.get(scope="Team", item_id=str(self.team.pk), activity="updated")
        assert log_entry.detail is not None
        change = log_entry.detail["changes"][0]
        assert change["field"] == "api_token"
        assert change["before"] == "phc_old_token_value"
        assert change["after"] == "phc_new_token_value"

    def test_set_token_and_save_rejects_token_already_taken_by_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, api_token="phc_already_taken")

        with self.assertRaises(ValueError) as ctx:
            self.team.set_token_and_save(
                new_token="phc_already_taken",
                user=self.user,
                is_impersonated_session=False,
            )
        assert "already in use" in str(ctx.exception)

        other_team.refresh_from_db()
        assert other_team.api_token == "phc_already_taken"
        self.team.refresh_from_db()
        assert self.team.api_token == "phc_old_token_value"

    def test_set_token_and_save_strips_whitespace(self) -> None:
        self.team.set_token_and_save(
            new_token="  phc_trimmed  ",
            user=self.user,
            is_impersonated_session=False,
        )
        self.team.refresh_from_db()
        assert self.team.api_token == "phc_trimmed"

    @patch("posthog.tasks.integrations.push_vercel_secrets.delay")
    @patch("posthog.models.team.team.set_team_in_cache")
    def test_set_token_and_save_accepts_token_at_field_max_length(self, _mock_set_cache, _mock_push_vercel) -> None:
        new_token = "a" * self.API_TOKEN_MAX_LENGTH
        self.team.set_token_and_save(
            new_token=new_token,
            user=self.user,
            is_impersonated_session=False,
        )
        self.team.refresh_from_db()
        assert self.team.api_token == new_token

    @patch("posthog.tasks.integrations.push_vercel_secrets.delay")
    def test_set_token_and_save_evicts_old_and_warms_new_cache(self, _mock_push_vercel) -> None:
        cache.clear()
        set_team_in_cache("phc_old_token_value", self.team)
        assert get_team_in_cache("phc_old_token_value") is not None

        self.team.set_token_and_save(
            new_token="phc_new_token_value",
            user=self.user,
            is_impersonated_session=False,
        )

        assert get_team_in_cache("phc_old_token_value") is None

        cached_new = get_team_in_cache("phc_new_token_value")
        assert cached_new is not None
        assert cached_new.api_token == "phc_new_token_value"

    @patch("posthog.tasks.integrations.push_vercel_secrets.delay")
    def test_set_token_and_save_rejection_leaves_cache_untouched(self, _mock_push_vercel) -> None:
        Team.objects.create(organization=self.organization, api_token="phc_already_taken")
        cache.clear()
        set_team_in_cache("phc_old_token_value", self.team)

        with self.assertRaises(ValueError):
            self.team.set_token_and_save(
                new_token="phc_already_taken",
                user=self.user,
                is_impersonated_session=False,
            )

        cached = get_team_in_cache("phc_old_token_value")
        assert cached is not None
        assert cached.api_token == "phc_old_token_value"
        assert get_team_in_cache("phc_already_taken") is None


class TestTeamProjectProvisioning(BaseTest):
    @parameterized.expand([("get_or_create",), ("update_or_create",)])
    def test_manager_shortcut_provisions_parent_project(self, method_name: str) -> None:
        # get_or_create / update_or_create delegate to QuerySet.create, which used to bypass the
        # project-provisioning path and leave project_id NULL, tripping project_id_is_not_null.
        kwargs: dict = {"organization": self.organization, "name": f"Provisioned via {method_name}"}
        if method_name == "update_or_create":
            kwargs["defaults"] = {}
        team, created = getattr(Team.objects, method_name)(**kwargs)

        self.assertTrue(created)
        self.assertIsNotNone(team.project_id)
        self.assertEqual(team.project_id, team.id)
        self.assertTrue(Project.objects.filter(id=team.project_id).exists())

    @parameterized.expand([("create",), ("get_or_create",)])
    def test_project_manager_shortcut_assigns_shared_sequence_id(self, method_name: str) -> None:
        # Project.id has no autofield — it's drawn from the shared sequence. A bare create without
        # an explicit id used to leave id NULL and violate the posthog_project PK not-null.
        result = getattr(Project.objects, method_name)(
            organization=self.organization, name=f"Standalone via {method_name}"
        )
        project = result[0] if method_name == "get_or_create" else result

        self.assertIsNotNone(project.id)
        self.assertTrue(Project.objects.filter(id=project.id).exists())

    def test_increment_id_sequence_recovers_from_lagging_sequence(self) -> None:
        # A DB restore / fixture seed can leave the shared sequence behind existing rows, so a plain
        # nextval hands back an already-used id. Guard against the resulting duplicate-PK crash.
        highest = max(
            Team.objects.order_by("-id").values_list("id", flat=True).first() or 0,
            Project.objects.order_by("-id").values_list("id", flat=True).first() or 0,
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT setval('posthog_team_id_seq', %s, true)", [max(highest - 5, 1)])

        next_id = Team.objects.increment_id_sequence()

        self.assertGreater(next_id, highest)
