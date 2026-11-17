from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import NonAtomicAPIBaseTest
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.models.role import Role, RoleMembership
from products.access_control.backend.presentation.role import RoleSerializer
from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.enums import Action

from ee.api.test.base import APILicensedTest, LicensedTestMixin


class TestRoleOrganizationAccessLevel(TestCase):
    def test_no_grant_by_default(self) -> None:
        organization = Organization.objects.create(name="Example")
        role = Role.objects.create(name="Default", organization=organization)
        role.refresh_from_db()
        self.assertIsNone(role.organization_access_level)

    @parameterized.expand([(None,), (OrganizationMembership.Level.ADMIN,)])
    def test_valid_grant_round_trip(self, level: int | None) -> None:
        organization = Organization.objects.create(name="Example")
        role = Role(name="Grant", organization=organization, organization_access_level=level)
        role.full_clean(exclude=["created_by"])
        role.save()
        role.refresh_from_db()
        self.assertEqual(role.organization_access_level, level)
        role.organization_access_level = None
        role.save(update_fields=["organization_access_level"])
        role.refresh_from_db()
        self.assertIsNone(role.organization_access_level)

    @parameterized.expand(
        [(OrganizationMembership.Level.MEMBER,), (OrganizationMembership.Level.OWNER,), (-1,), (0,), (9,)]
    )
    def test_model_validation_rejects_other_levels(self, level: int) -> None:
        organization = Organization.objects.create(name="Example")
        role = Role(name="Invalid", organization=organization, organization_access_level=level)
        with self.assertRaises(ValidationError) as error:
            role.full_clean(exclude=["created_by"])
        self.assertIn("organization_access_level", error.exception.message_dict)

    @parameterized.expand(
        [(OrganizationMembership.Level.MEMBER,), (OrganizationMembership.Level.OWNER,), (-1,), (0,), (9,)]
    )
    def test_database_rejects_other_levels(self, level: int) -> None:
        organization = Organization.objects.create(name="Example")
        role = Role.objects.create(name="Grant", organization=organization)
        with self.assertRaisesMessage(IntegrityError, "role_org_access_level_admin_or_null"), transaction.atomic():
            Role.objects.filter(pk=role.pk).update(organization_access_level=level)
        role.refresh_from_db()
        self.assertIsNone(role.organization_access_level)


class TestRoleCrossOrgAuthorization(APILicensedTest):
    """Tests for cross-organization authorization bypass on role endpoints."""

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.org_a = self.organization
        self.org_b = Organization.objects.create(name="Org B")
        self.org_b.update_available_product_features()
        self.org_b.save()

        # User is admin in org_a, member in org_b
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.org_b_membership = OrganizationMembership.objects.create(
            user=self.user, organization=self.org_b, level=OrganizationMembership.Level.MEMBER
        )

    def _switch_active_org(self, org):
        self.user.current_organization = org
        self.user.save()

    def test_cross_org_admin_cannot_create_roles_in_other_org(self):
        self._switch_active_org(self.org_a)
        res = self.client.post(f"/api/organizations/{self.org_b.id}/roles", {"name": "Hacked Role"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_org_admin_cannot_update_roles_in_other_org(self):
        role = Role.objects.create(name="Engineering", organization=self.org_b)
        self._switch_active_org(self.org_a)
        res = self.client.patch(f"/api/organizations/{self.org_b.id}/roles/{role.id}", {"name": "Hacked"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_org_admin_cannot_delete_roles_in_other_org(self):
        role = Role.objects.create(name="Engineering", organization=self.org_b)
        self._switch_active_org(self.org_a)
        res = self.client.delete(f"/api/organizations/{self.org_b.id}/roles/{role.id}")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_org_role_creation_uses_correct_org(self):
        """Admin in both orgs, active=A, POST to B URL → role.organization == B"""
        self.org_b_membership.level = OrganizationMembership.Level.ADMIN
        self.org_b_membership.save()
        self._switch_active_org(self.org_a)
        res = self.client.post(f"/api/organizations/{self.org_b.id}/roles", {"name": "New Role"})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        role = Role.objects.get(id=res.json()["id"])
        self.assertEqual(role.organization_id, self.org_b.id)

    def test_cross_org_role_name_uniqueness_checks_correct_org(self):
        """'Engineering' exists in A. Admin in both, active=A, POST to B → 201"""
        Role.objects.create(name="Engineering", organization=self.org_a)
        self.org_b_membership.level = OrganizationMembership.Level.ADMIN
        self.org_b_membership.save()
        self._switch_active_org(self.org_a)
        res = self.client.post(f"/api/organizations/{self.org_b.id}/roles", {"name": "Engineering"})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_member_cannot_modify_roles_after_fix(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        res = self.client.post(f"/api/organizations/{self.org_a.id}/roles", {"name": "Blocked"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_modify_roles_with_explicit_org_id(self):
        res = self.client.post(f"/api/organizations/{self.org_a.id}/roles", {"name": "Allowed"})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)


class TestRoleAPI(APILicensedTest):
    def test_only_organization_admins_and_higher_can_create(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        admin_create_res = self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "Product",
            },
        )

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        member_create_res = self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "Product 2",
            },
        )
        self.assertEqual(admin_create_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Role.objects.all().count(), 1)
        self.assertEqual(Role.objects.first().name, "Product")  # type: ignore
        self.assertEqual(member_create_res.status_code, status.HTTP_403_FORBIDDEN)

    def test_only_organization_admins_and_higher_can_update(self):
        existing_eng_role = Role.objects.create(
            name="Engineering",
            organization=self.organization,
            created_by=self.user,
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        admin_update_res = self.client.patch(
            f"/api/organizations/@current/roles/{existing_eng_role.id}",
            {"name": "on call support"},
        )

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        member_update_res = self.client.patch(
            f"/api/organizations/@current/roles/{existing_eng_role.id}",
            {"name": "member eng"},
        )

        self.assertEqual(admin_update_res.status_code, status.HTTP_200_OK)
        self.assertEqual(member_update_res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Role.objects.all().count(), 1)
        self.assertEqual(Role.objects.first().name, "on call support")  # type: ignore

    def test_cannot_duplicate_role_name(self):
        Role.objects.create(name="Marketing", organization=self.organization)
        count = Role.objects.count()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        res = self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "marketing",
            },
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.json(),
            {
                "type": "validation_error",
                "code": "unique",
                "detail": "There is already a role with this name.",
                "attr": "name",
            },
        )
        self.assertEqual(Role.objects.count(), count)
        other_org = Organization.objects.create(name="other org")
        Role.objects.create(name="Marketing", organization=other_org)
        self.assertEqual(Role.objects.count(), 2)
        self.assertEqual(Role.objects.filter(organization=other_org).exists(), True)
        with self.assertRaises(IntegrityError):
            Role.objects.create(name="Marketing", organization=self.organization)

    def test_can_rename_role_with_case_change(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        role = Role.objects.create(name="engineering", organization=self.organization, created_by=self.user)
        res = self.client.patch(
            f"/api/organizations/@current/roles/{role.id}",
            {"name": "Engineering"},
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        role.refresh_from_db()
        self.assertEqual(role.name, "Engineering")

    def test_cannot_rename_role_to_existing_name(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        Role.objects.create(name="Marketing", organization=self.organization, created_by=self.user)
        eng_role = Role.objects.create(name="Engineering", organization=self.organization, created_by=self.user)
        res = self.client.patch(
            f"/api/organizations/@current/roles/{eng_role.id}",
            {"name": "marketing"},
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()["code"], "unique")

    @parameterized.expand([("roles",), ("members",), ("role_memberships",)])
    def test_listing_roles_does_not_scale_queries_with_member_count(self, endpoint: str):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        role = Role.objects.create(name="Engineering", organization=self.organization, organization_access_level=8)

        def add_members(count: int) -> None:
            for _ in range(count):
                user = User.objects.create_and_join(self.organization, f"member-{uuid4()}@posthog.com", None)
                membership = OrganizationMembership.objects.get(organization=self.organization, user=user)
                RoleMembership.objects.create(role=role, user=user, organization_member=membership)

        url = (
            f"/api/organizations/@current/roles/{role.id}/role_memberships"
            if endpoint == "role_memberships"
            else f"/api/organizations/@current/{endpoint}"
        )

        def members_for_role(response) -> list:
            if endpoint == "role_memberships":
                return response.json()["results"]
            if endpoint == "members":
                return [r for r in response.json()["results"] if r["role_grants"]]
            return next(r["members"] for r in response.json()["results"] if r["id"] == str(role.id))

        # Warm up per-process caches (instance settings etc.) so they don't skew the counts below.
        self.client.get(url)

        add_members(2)
        with CaptureQueriesContext(connection) as few_members:
            res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(members_for_role(res)), 2)

        add_members(4)
        with CaptureQueriesContext(connection) as more_members:
            res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(members_for_role(res)), 6)

        # Constant query count as members grow: the social-auth/2FA lookups are prefetched, not N+1.
        self.assertEqual(len(few_members.captured_queries), len(more_members.captured_queries))

    def test_returns_correct_results_by_organization(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "Product",
            },
        )
        self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "Customer Success",
            },
        )
        other_org = Organization.objects.create(name="other org")
        Role.objects.create(name="Product", organization=other_org)
        self.assertEqual(Role.objects.count(), 3)
        res = self.client.get("/api/organizations/@current/roles")
        results = res.json()
        self.assertEqual(results["count"], 2)
        self.assertNotContains(res, str(other_org.id))


class TestRoleMemberVisibilityRestriction(APILicensedTest):
    """When members_can_see_org_members is off, role endpoints must not disclose members the
    requester can't see in the members list."""

    def setUp(self):
        super().setUp()
        from posthog.constants import AvailableFeature

        from products.access_control.backend.models.access_control import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.members_can_see_org_members = False
        self.organization.save()

        self.mate = User.objects.create_and_join(self.organization, "mate@posthog.com", None)
        self.hidden = User.objects.create_and_join(self.organization, "hidden@posthog.com", None)
        self.role = Role.objects.create(name="Engineering", organization=self.organization, created_by=self.hidden)
        for user in [self.mate, self.hidden]:
            RoleMembership.objects.create(
                role=self.role,
                user=user,
                organization_member=user.organization_memberships.get(organization=self.organization),
            )
        # Private project: explicit access for the requester and one project mate, none for `hidden`
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
        )
        for membership in [
            self.organization_membership,
            self.mate.organization_memberships.get(organization=self.organization),
        ]:
            AccessControl.objects.create(
                team=self.team,
                resource="project",
                resource_id=str(self.team.id),
                organization_member=membership,
                access_level="member",
            )

    def test_restricted_member_cannot_see_hidden_members_via_roles(self):
        response = self.client.get("/api/organizations/@current/roles")
        assert response.status_code == status.HTTP_200_OK
        role = response.json()["results"][0]
        assert {m["user"]["email"] for m in role["members"]} == {self.mate.email}
        assert role["created_by"] is None

    def test_restricted_member_cannot_see_hidden_members_via_role_memberships(self):
        response = self.client.get(f"/api/organizations/@current/roles/{self.role.id}/role_memberships")
        assert response.status_code == status.HTTP_200_OK
        assert {m["user"]["email"] for m in response.json()["results"]} == {self.mate.email}

    def test_admin_still_sees_all_role_members(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.get("/api/organizations/@current/roles")
        role = response.json()["results"][0]
        assert {m["user"]["email"] for m in role["members"]} == {self.mate.email, self.hidden.email}
        assert role["created_by"]["email"] == self.hidden.email


class TestOrganizationRoleGrantAPI(APILicensedTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.role = Role.objects.create(name="Administrators", organization=self.organization)
        self.member = User.objects.create_and_join(self.organization, "member@example.com", None)

    @parameterized.expand([(True, 200), (False, 400), (None, 400)])
    def test_mapping_promotion_requires_rollout(self, enabled: bool | None, expected: int) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=enabled):
            response = self.client.patch(
                f"/api/organizations/{self.organization.id}/roles/{self.role.id}",
                {"organization_access_level": 8},
            )
        assert response.status_code == expected
        self.role.refresh_from_db()
        assert self.role.organization_access_level == (8 if enabled else None)
        if enabled:
            log = ActivityLog.objects.filter(scope="Role", item_id=self.role.id, activity="updated").latest(
                "created_at"
            )
            assert log.detail is not None
            assert log.user_id == self.user.id
            assert any(c["field"] == "organization_access_level" and c["after"] == 8 for c in log.detail["changes"])

    def test_mapping_can_be_cleared_when_rollout_is_disabled(self) -> None:
        self.role.organization_access_level = 8
        self.role.save()
        with patch("posthoganalytics.feature_enabled", return_value=False):
            response = self.client.patch(
                f"/api/organizations/{self.organization.id}/roles/{self.role.id}",
                {"organization_access_level": None},
            )
        assert response.status_code == 200
        self.role.refresh_from_db()
        assert self.role.organization_access_level is None

    @parameterized.expand([("mapping",), ("member",), ("default",), ("delete",), ("remove_member",)])
    def test_edit_permission_cannot_manage_organization_grants(self, operation: str) -> None:
        if operation != "mapping":
            self.role.organization_access_level = 8
            self.role.save()
        if operation == "remove_member":
            role_membership = RoleMembership.objects.create(
                role=self.role,
                user=self.member,
                organization_member=OrganizationMembership.objects.get(
                    organization=self.organization, user=self.member
                ),
            )
        original_check = authorization.check

        def check(*args, **kwargs):
            if kwargs.get("action") == Action.MANAGE_ACCESS:
                return False
            return original_check(*args, **kwargs)

        with patch.object(authorization, "check", side_effect=check):
            if operation == "mapping":
                response = self.client.patch(
                    f"/api/organizations/{self.organization.id}/roles/{self.role.id}",
                    {"organization_access_level": 8},
                )
            elif operation == "member":
                response = self.client.post(
                    f"/api/organizations/{self.organization.id}/roles/{self.role.id}/role_memberships",
                    {"user_uuid": str(self.member.uuid)},
                )
            elif operation == "default":
                response = self.client.patch(
                    f"/api/organizations/{self.organization.id}", {"default_role_id": str(self.role.id)}
                )
            elif operation == "remove_member":
                response = self.client.delete(
                    f"/api/organizations/{self.organization.id}/roles/{self.role.id}/role_memberships/{role_membership.id}"
                )
            else:
                response = self.client.delete(f"/api/organizations/{self.organization.id}/roles/{self.role.id}")
        assert response.status_code == 403
        self.role.refresh_from_db()
        self.organization.refresh_from_db()
        assert self.role.organization_access_level == (None if operation == "mapping" else 8)
        assert self.organization.default_role_id is None
        assert RoleMembership.objects.filter(role=self.role, user=self.member).exists() == (
            operation == "remove_member"
        )

    def test_stale_role_cannot_bypass_grant_management(self) -> None:
        request = Request(APIRequestFactory().patch("/"))
        request.user = self.user
        serializer = RoleSerializer(
            self.role,
            data={"name": "Renamed"},
            partial=True,
            context={"request": request, "view": SimpleNamespace(organization=self.organization)},
        )
        assert serializer.is_valid(), serializer.errors
        Role.objects.filter(pk=self.role.pk).update(organization_access_level=8)
        with patch.object(authorization, "check", return_value=False), self.assertRaises(PermissionDenied):
            serializer.save()
        self.role.refresh_from_db()
        assert self.role.name == "Administrators"
        assert self.role.organization_access_level == 8

    def test_api_rejects_owner_grant(self) -> None:
        response = self.client.patch(
            f"/api/organizations/{self.organization.id}/roles/{self.role.id}",
            {"organization_access_level": OrganizationMembership.Level.OWNER},
        )
        assert response.status_code == 400
        self.role.refresh_from_db()
        assert self.role.organization_access_level is None

    @parameterized.expand([(False, 1), (True, 8)])
    def test_direct_downgrade_returns_current_effective_access(self, granted: bool, expected: int) -> None:
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()
        if granted:
            self.role.organization_access_level = 8
            self.role.save()
            RoleMembership.objects.create(role=self.role, user=self.member, organization_member=membership)
        response = self.client.patch(
            f"/api/organizations/{self.organization.id}/members/{self.member.uuid}", {"level": 1}
        )
        assert response.status_code == 200
        assert response.json()["level"] == 1
        assert response.json()["effective_level"] == expected

    @parameterized.expand([("role",), ("membership",)])
    @override_settings(ACTIVITY_LOG_TRANSACTION_MANAGEMENT=True)
    def test_rolled_back_deletion_does_not_write_audit(self, target: str) -> None:
        self.role.organization_access_level = 8
        self.role.save()
        membership = RoleMembership.objects.create(role=self.role, user=self.member)
        before = ActivityLog.objects.filter(scope="Role", item_id=self.role.id).count()
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    if target == "role":
                        Role.objects.filter(pk=self.role.pk).delete()
                    else:
                        RoleMembership.objects.filter(pk=membership.pk).delete()
                    raise ValueError("Roll back the deletion")
            except ValueError:
                pass
        assert RoleMembership.objects.filter(pk=membership.pk).exists()
        assert ActivityLog.objects.filter(scope="Role", item_id=self.role.id).count() == before

    def test_member_response_distinguishes_direct_access_and_grants(self) -> None:
        self.role.organization_access_level = 8
        self.role.save()
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)
        role_membership = RoleMembership.objects.create(
            role=self.role, user=self.member, organization_member=membership
        )
        other_org = Organization.objects.create(name="Other organization")
        other_role = Role.objects.create(
            organization=other_org, name="Other administrators", organization_access_level=8
        )
        RoleMembership.objects.create(role=other_role, user=self.member)
        response = self.client.get(f"/api/organizations/{self.organization.id}/members", {"email": self.member.email})
        assert response.status_code == 200
        assert response.json()["results"][0]["level"] == OrganizationMembership.Level.MEMBER
        assert response.json()["results"][0]["effective_level"] == 8
        assert response.json()["results"][0]["role_grants"] == [
            {"id": str(self.role.id), "name": self.role.name, "organization_access_level": 8}
        ]
        role_membership.delete()
        response = self.client.get(f"/api/organizations/{self.organization.id}/members", {"email": self.member.email})
        assert response.json()["results"][0]["effective_level"] == OrganizationMembership.Level.MEMBER
        assert response.json()["results"][0]["role_grants"] == []
        activities = ActivityLog.objects.filter(scope="Role", item_id=self.role.id, activity="updated")
        member_changes = [c for log in activities for c in (log.detail or {})["changes"] if c["field"] == "members"]
        assert {c["action"] for c in member_changes} == {"created", "deleted"}


class TestOrganizationRoleGrantValidation(SimpleTestCase):
    @parameterized.expand([(1,), (15,), (0,), (9,)])
    def test_only_admin_grants_are_accepted(self, level: int) -> None:
        serializer = RoleSerializer(data={"organization_access_level": level}, partial=True)
        assert not serializer.is_valid()
        assert serializer.errors["organization_access_level"][0].code == "invalid_choice"


class TestOrganizationRoleGrantWriteRace(LicensedTestMixin, NonAtomicAPIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @parameterized.expand([("member",), ("default",), ("rename",)])
    def test_permission_is_rechecked_after_concurrent_promotion(self, operation: str) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        role = Role.objects.create(name="Ordinary", organization=self.organization)
        target = User.objects.create_and_join(self.organization, "target@example.com", None)
        waiting_for_role = Event()

        def perform_request():
            def observe_lock(execute, sql, params, many, context):
                if '"ee_role"' in sql and "FOR NO KEY UPDATE" in sql:
                    waiting_for_role.set()
                return execute(sql, params, many, context)

            try:
                with connection.execute_wrapper(observe_lock):
                    if operation == "member":
                        return self.client.post(
                            f"/api/organizations/{self.organization.id}/roles/{role.id}/role_memberships",
                            {"user_uuid": str(target.uuid)},
                        )
                    if operation == "default":
                        return self.client.patch(
                            f"/api/organizations/{self.organization.id}", {"default_role_id": str(role.id)}
                        )
                    return self.client.patch(
                        f"/api/organizations/{self.organization.id}/roles/{role.id}", {"name": "Renamed"}
                    )
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                Role.objects.select_for_update(no_key=True).get(pk=role.pk)
                result = executor.submit(perform_request)
                assert waiting_for_role.wait(timeout=30), "Request did not reach the role lock"
                Role.objects.filter(pk=role.pk).update(organization_access_level=8)
                OrganizationMembership.objects.filter(pk=self.organization_membership.pk).update(level=1)
            response = result.result(timeout=30)
        assert response.status_code == 403
        role.refresh_from_db()
        self.organization.refresh_from_db()
        assert role.name == "Ordinary"
        assert self.organization.default_role_id is None
        assert not RoleMembership.objects.filter(role=role).exists()
