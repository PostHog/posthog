from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from posthog.test.base import BaseTest, NonAtomicBaseTest
from unittest.mock import patch

import django
from django.conf import settings
from django.core.cache import caches
from django.db import connections, transaction
from django.db.models import Prefetch
from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, User
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.organization_caching import get_cached_organization_membership, get_cached_organization_memberships
from posthog.settings.utils import generate_rsa_private_key_pem
from posthog.storage.gateway_credential_cache import (
    credential_hash,
    gateway_credential_hypercache,
    project_gateway_credential,
)
from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade.testing import create_access_control
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType


class TestOrganizationRoleAccess(BaseTest):
    @parameterized.expand(
        [
            (OrganizationMembership.Level.MEMBER, OrganizationMembership.Level.ADMIN),
            (OrganizationMembership.Level.ADMIN, OrganizationMembership.Level.ADMIN),
            (OrganizationMembership.Level.OWNER, OrganizationMembership.Level.OWNER),
        ]
    )
    def test_effective_access_keeps_direct_assignment(self, assigned: int, expected: int) -> None:
        self.organization_membership.level = assigned
        self.organization_membership.save()
        role = Role.objects.create(
            organization=self.organization,
            name="Administrators",
            organization_access_level=OrganizationMembership.Level.ADMIN,
        )
        RoleMembership.objects.create(role=role, user=self.user, organization_member=self.organization_membership)
        with self.assertNumQueries(1):
            membership = OrganizationMembership.objects.with_effective_level().get(pk=self.organization_membership.pk)
            assert membership.effective_level == expected
            assert membership.resolved_level == expected
            assert membership.level == assigned
        assert self.organization_membership.effective_level == expected

    @parameterized.expand(
        [("legacy", None), ("bound", "self"), ("different_member", "other"), ("previous_membership", "previous")]
    )
    def test_grants_apply_only_to_the_matching_member(self, _name: str, binding: str | None) -> None:
        other = User.objects.create_and_join(self.organization, "other@example.com", None)
        member = other.organization_memberships.get(organization=self.organization)
        role = Role.objects.create(
            organization=self.organization,
            name="Administrators",
            organization_access_level=OrganizationMembership.Level.ADMIN,
        )
        link = RoleMembership.objects.create(
            role=role,
            user=self.user,
            organization_member=self.organization_membership
            if binding == "self"
            else member
            if binding == "other"
            else None,
        )
        if binding == "previous":
            RoleMembership.objects.filter(pk=link.pk).update(
                joined_at=self.organization_membership.joined_at - timedelta(days=1)
            )
        expected = (
            OrganizationMembership.Level.MEMBER
            if binding in ("other", "previous")
            else OrganizationMembership.Level.ADMIN
        )
        assert self.organization_membership.effective_level == expected
        resolved = OrganizationMembership.objects.with_effective_level().get(pk=self.organization_membership.pk)
        assert resolved.effective_level == resolved.resolved_level == expected
        assert resolved.organization_access_role_grants == (
            [role] if expected == OrganizationMembership.Level.ADMIN else []
        )
        assert member.effective_level == OrganizationMembership.Level.MEMBER

    def test_other_organization_roles_cannot_grant_access(self) -> None:
        other = Organization.objects.create(name="Other")
        role = Role.objects.create(
            organization=other, name="Administrators", organization_access_level=OrganizationMembership.Level.ADMIN
        )
        RoleMembership.objects.create(role=role, user=self.user, organization_member=self.organization_membership)
        assert self.organization_membership.effective_level == OrganizationMembership.Level.MEMBER

    def test_multiple_roles_keep_access_until_last_grant_is_removed(self) -> None:
        first = Role.objects.create(
            organization=self.organization, name="First", organization_access_level=OrganizationMembership.Level.ADMIN
        )
        second = Role.objects.create(
            organization=self.organization, name="Second", organization_access_level=OrganizationMembership.Level.ADMIN
        )
        RoleMembership.objects.create(role=first, user=self.user, organization_member=self.organization_membership)
        RoleMembership.objects.create(role=second, user=self.user, organization_member=self.organization_membership)
        first.delete()
        self.assertEqual(self.organization_membership.effective_level, OrganizationMembership.Level.ADMIN)
        second.organization_access_level = None
        second.save()
        assert self.organization_membership.effective_level == OrganizationMembership.Level.MEMBER

    def test_no_ee_falls_back_to_direct_access(self) -> None:
        membership_id = self.organization_membership.pk
        with patch("posthog.models.organization.apps.get_model", side_effect=LookupError):
            with self.assertNumQueries(1):
                member = OrganizationMembership.objects.with_effective_level().get(pk=membership_id)
                assert member.effective_level == member.level == OrganizationMembership.Level.MEMBER
            assert member.organization_access_role_grants == []

    def test_batch_access_does_not_query_per_member(self) -> None:
        users = [User.objects.create_and_join(self.organization, f"member-{i}@example.com", None) for i in range(5)]
        role = Role.objects.create(
            organization=self.organization,
            name="Administrators",
            organization_access_level=OrganizationMembership.Level.ADMIN,
        )
        RoleMembership.objects.bulk_create([RoleMembership(role=role, user=user) for user in users])
        with self.assertNumQueries(1):
            members = list(OrganizationMembership.objects.with_effective_level().filter(user__in=users))
            assert [member.effective_level for member in members] == [OrganizationMembership.Level.ADMIN] * 5
        self.team.organization = self.organization
        with self.assertNumQueries(1):
            access = UserAccessControl.for_user_ids(user_ids=[user.pk for user in users], team=self.team)
            assert all(item.is_organization_admin for item in access.values())

    @parameterized.expand([(1,), (5,)])
    def test_project_member_enumeration_batches_role_grants(self, count: int) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        self.team.organization = self.organization
        create_access_control(
            team_id=self.team.id, resource="project", resource_id=str(self.team.id), access_level="none"
        )
        create_access_control(
            team_id=self.team.id,
            resource="project",
            resource_id=str(self.team.id),
            access_level="none",
            organization_member_id=self.organization_membership.pk,
        )
        users = [
            User.objects.create_and_join(self.organization, f"project-{i}@example.com", None) for i in range(count)
        ]
        role = Role.objects.create(
            organization=self.organization,
            name="Administrators",
            organization_access_level=OrganizationMembership.Level.ADMIN,
        )
        RoleMembership.objects.bulk_create([RoleMembership(role=role, user=user) for user in users])
        with self.assertNumQueries(3):
            assert set(self.team.all_users_with_access().values_list("pk", flat=True)) == {user.pk for user in users}

    def test_metadata_prefetch_matches_effective_resolution_without_extra_queries(self) -> None:
        grant = Role.objects.create(
            organization=self.organization, name="Grant", organization_access_level=OrganizationMembership.Level.ADMIN
        )
        ordinary = Role.objects.create(organization=self.organization, name="Ordinary")
        RoleMembership.objects.create(role=grant, user=self.user)
        RoleMembership.objects.create(role=ordinary, user=self.user)
        with self.assertNumQueries(2):
            member = (
                OrganizationMembership.objects.with_effective_level()
                .select_related("user")
                .prefetch_related(
                    Prefetch(
                        "user__role_memberships",
                        queryset=RoleMembership.objects.select_related("role"),
                        to_attr="organization_access_role_memberships",
                    )
                )
                .get(pk=self.organization_membership.pk)
            )
            assert member.effective_level == OrganizationMembership.Level.ADMIN
            assert member.organization_access_role_grants == [grant]

    @parameterized.expand(
        [
            (assigned, grant, OrganizationMembership.Level.ADMIN if grant else OrganizationMembership.Level.MEMBER)
            for assigned in (OrganizationMembership.Level.ADMIN, OrganizationMembership.Level.OWNER)
            for grant in (False, True)
        ]
    )
    def test_changing_direct_level_does_not_reuse_annotated_direct_admin(
        self, assigned: int, grant: bool, expected: int
    ) -> None:
        self.organization_membership.level = assigned
        self.organization_membership.save()
        if grant:
            role = Role.objects.create(
                organization=self.organization,
                name="Grant",
                organization_access_level=OrganizationMembership.Level.ADMIN,
            )
            RoleMembership.objects.create(role=role, user=self.user)
        member = OrganizationMembership.objects.with_effective_level().get(pk=self.organization_membership.pk)
        member.level = OrganizationMembership.Level.MEMBER
        with self.assertNumQueries(0):
            assert member.effective_level == expected
        member.save()
        assert member.effective_level == expected

    def test_explicit_preview_membership_is_not_replaced(self) -> None:
        preview = OrganizationMembership(
            organization=self.organization, user=self.user, level=OrganizationMembership.Level.ADMIN
        )
        with self.assertNumQueries(0):
            member = UserPermissions(self.user, organization_membership=preview).get_organization_membership(
                self.organization.id
            )
            assert member is not None and member is preview
            assert member.effective_level == OrganizationMembership.Level.ADMIN


class TestOrganizationRoleAccessCache(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        self.enterContext(self.settings(ORGANIZATION_ACCESS_CACHE_ENABLED=True))
        super().setUp()
        self.role = Role.objects.create(
            organization=self.organization,
            name="Administrators",
            organization_access_level=OrganizationMembership.Level.ADMIN,
        )

    def grant(self) -> RoleMembership:
        return RoleMembership.objects.create(
            role=self.role, user=self.user, organization_member=self.organization_membership
        )

    def assert_access(self, level: int) -> None:
        membership = get_cached_organization_membership(self.organization.id, self.user)
        assert membership is not None
        assert membership.effective_level == level
        assert get_cached_organization_memberships(self.user)[0].effective_level == level

    @parameterized.expand([("save",), ("update",), ("bulk_update",), ("delete_role",), ("delete_membership",)])
    def test_revocation_invalidates_single_and_list_caches(self, operation: str) -> None:
        self.grant()
        self.assert_access(OrganizationMembership.Level.ADMIN)
        if operation == "save":
            self.role.organization_access_level = None
            self.role.save()
        elif operation == "update":
            Role.objects.filter(pk=self.role.pk).update(organization_access_level=None)
        elif operation == "bulk_update":
            self.role.organization_access_level = None
            Role.objects.bulk_update([self.role], ["organization_access_level"])
        elif operation == "delete_role":
            Role.objects.filter(pk=self.role.pk).delete()
        else:
            RoleMembership.objects.filter(role=self.role).delete()
        self.assert_access(OrganizationMembership.Level.MEMBER)

    @parameterized.expand([("role_grant",), ("role_membership",)])
    def test_revocation_refreshes_gateway_credential_after_cache_invalidation(self, operation: str) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        self.user.is_email_verified = True
        self.user.save()
        create_access_control(
            team_id=self.team.id, resource="project", resource_id=str(self.team.id), access_level="none"
        )
        create_access_control(
            team_id=self.team.id,
            resource="project",
            resource_id=str(self.team.id),
            access_level="none",
            organization_member_id=self.organization_membership.pk,
        )
        link = self.grant()
        self.enterContext(
            self.settings(
                OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_private_key_pem()}
            )
        )
        application = OAuthApplication.objects.create(
            algorithm="RS256",
            name="Role access test",
            organization=self.organization,
            user=self.user,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
        )
        credential = OAuthAccessToken.objects.create(
            application=application,
            user=self.user,
            token="pha_role_access_test",
            scope="llm_gateway:read",
            expires=timezone.now() + timedelta(hours=1),
        )
        project_gateway_credential(credential)
        cache_hash = credential_hash(credential)
        assert cache_hash is not None
        cache_key = gateway_credential_hypercache.get_cache_key(cache_hash)
        assert gateway_credential_hypercache.cache_client.get(cache_key) not in (None, "__missing__")
        self.assert_access(OrganizationMembership.Level.ADMIN)
        with self.settings(AI_GATEWAY_REDIS_URL="redis://localhost:6379/15"):
            with transaction.atomic():
                Role.objects.filter(pk=self.role.pk).update(organization_access_level=None)
                transaction.set_rollback(True)
            assert gateway_credential_hypercache.cache_client.get(cache_key) not in (None, "__missing__")
            if operation == "role_grant":
                Role.objects.filter(pk=self.role.pk).update(organization_access_level=None)
            else:
                link.delete()
        assert gateway_credential_hypercache.cache_client.get(cache_key) in (None, "__missing__")
        self.assert_access(OrganizationMembership.Level.MEMBER)

    def test_grant_bulk_create_and_membership_change_invalidate_caches(self) -> None:
        self.assert_access(OrganizationMembership.Level.MEMBER)
        RoleMembership.objects.bulk_create([RoleMembership(role=self.role, user=self.user)])
        self.assert_access(OrganizationMembership.Level.ADMIN)
        other = User.objects.create_and_join(self.organization, "other@example.com", None)
        RoleMembership.objects.filter(role=self.role).update(
            user=other, organization_member=other.organization_memberships.get(organization=self.organization)
        )
        self.assert_access(OrganizationMembership.Level.MEMBER)
        other_member = get_cached_organization_membership(self.organization.id, other)
        assert other_member is not None and other_member.effective_level == OrganizationMembership.Level.ADMIN

    @parameterized.expand([("grant", False), ("revoke", True)])
    def test_transaction_reads_own_changes_and_rollback_keeps_cache(self, _name: str, granted: bool) -> None:
        if granted:
            self.grant()
        original = OrganizationMembership.Level.ADMIN if granted else OrganizationMembership.Level.MEMBER
        self.assert_access(original)
        with transaction.atomic():
            if granted:
                RoleMembership.objects.filter(role=self.role).delete()
            else:
                self.grant()
            self.assert_access(OrganizationMembership.Level.MEMBER if granted else OrganizationMembership.Level.ADMIN)
            transaction.set_rollback(True)
        with self.assertNumQueries(0):
            self.assert_access(original)

    def test_leave_rejoin_drops_legacy_grants_only_in_that_organization(self) -> None:
        RoleMembership.objects.create(role=self.role, user=self.user)
        other_org = Organization.objects.create(name="Other")
        other_role = Role.objects.create(
            organization=other_org,
            name="Other administrators",
            organization_access_level=OrganizationMembership.Level.ADMIN,
        )
        other_link = RoleMembership.objects.create(role=other_role, user=self.user)
        self.assert_access(OrganizationMembership.Level.ADMIN)
        with transaction.atomic():
            OrganizationMembership.objects.filter(pk=self.organization_membership.pk).delete()
            assert not RoleMembership.objects.filter(role=self.role).exists()
            transaction.set_rollback(True)
        self.assert_access(OrganizationMembership.Level.ADMIN)
        OrganizationMembership.objects.filter(pk=self.organization_membership.pk).delete()
        assert RoleMembership.objects.filter(pk=other_link.pk).exists()
        self.organization_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.user
        )
        self.assert_access(OrganizationMembership.Level.MEMBER)

    def test_sdk_actions_and_same_session_bulk_revocation(self) -> None:
        resource = Resource(type=ResourceType.ORGANIZATION, id=str(self.organization.pk))
        subject = Subject(user_id=self.user.pk)
        with authorization.authorization_session():
            assert not authorization.check(resource=resource, action=Action.EDIT, subject=subject)
            RoleMembership.objects.bulk_create([RoleMembership(role=self.role, user=self.user)])
            assert authorization.check(resource=resource, action=Action.EDIT, subject=subject)
            assert not authorization.check(resource=resource, action=Action.DELETE, subject=subject)
            assert not authorization.check(resource=resource, action=Action.MANAGE_OWNERS, subject=subject)
            Role.objects.filter(pk=self.role.pk).update(organization_access_level=None)
            assert not authorization.check(resource=resource, action=Action.EDIT, subject=subject)

    @parameterized.expand([("enabled", True, 2), ("disabled", False, 1)])
    def test_list_loads_effective_levels_in_bounded_queries(self, _name: str, enabled: bool, count: int) -> None:
        self.grant()
        for i in range(4):
            org = Organization.objects.create(name=f"Other {i}")
            member = OrganizationMembership.objects.create(organization=org, user=self.user)
            role = Role.objects.create(
                organization=org, name="Administrators", organization_access_level=OrganizationMembership.Level.ADMIN
            )
            RoleMembership.objects.create(role=role, user=self.user, organization_member=member)
        with self.settings(ORGANIZATION_ACCESS_CACHE_ENABLED=enabled):
            with self.assertNumQueries(count):
                assert [member.effective_level for member in get_cached_organization_memberships(self.user)] == [
                    OrganizationMembership.Level.ADMIN
                ] * 5
            if enabled:
                with self.assertNumQueries(0):
                    assert [member.effective_level for member in get_cached_organization_memberships(self.user)] == [
                        OrganizationMembership.Level.ADMIN
                    ] * 5

    def test_role_admin_can_assign_a_separate_direct_admin_grant(self) -> None:
        self.grant()
        target = User.objects.create_and_join(self.organization, "direct-admin@example.com", None)
        membership = target.organization_memberships.get(organization=self.organization)
        self.organization_membership.validate_update(membership, OrganizationMembership.Level.ADMIN)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()
        self.role.organization_access_level = None
        self.role.save()
        self.assert_access(OrganizationMembership.Level.MEMBER)
        assert membership.effective_level == OrganizationMembership.Level.ADMIN

    def test_direct_admin_survives_role_revocation(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.grant()
        self.assert_access(OrganizationMembership.Level.ADMIN)
        self.role.delete()
        self.assert_access(OrganizationMembership.Level.ADMIN)

    @parameterized.expand([("save", False), ("update", True)])
    def test_moving_role_invalidates_old_and_new_organizations(self, _name: str, bulk: bool) -> None:
        other = Organization.objects.create(name="Other")
        OrganizationMembership.objects.create(organization=other, user=self.user)
        RoleMembership.objects.create(role=self.role, user=self.user)
        self.assert_access(OrganizationMembership.Level.ADMIN)
        other_member = get_cached_organization_membership(other.id, self.user)
        assert other_member is not None and other_member.effective_level == OrganizationMembership.Level.MEMBER
        if bulk:
            Role.objects.filter(pk=self.role.pk).update(organization=other)
        else:
            self.role.organization = other
            self.role.save()
        previous_member = get_cached_organization_membership(self.organization.id, self.user)
        other_member = get_cached_organization_membership(other.id, self.user)
        assert previous_member is not None and previous_member.effective_level == OrganizationMembership.Level.MEMBER
        assert other_member is not None and other_member.effective_level == OrganizationMembership.Level.ADMIN
        assert {m.organization_id: m.effective_level for m in get_cached_organization_memberships(self.user)} == {
            self.organization.id: OrganizationMembership.Level.MEMBER,
            other.id: OrganizationMembership.Level.ADMIN,
        }

    def test_membership_bulk_update_revokes_mismatched_binding(self) -> None:
        link = self.grant()
        other = User.objects.create_and_join(self.organization, "bound@example.com", None)
        self.assert_access(OrganizationMembership.Level.ADMIN)
        link.organization_member = other.organization_memberships.get(organization=self.organization)
        RoleMembership.objects.bulk_update([link], ["organization_member"])
        self.assert_access(OrganizationMembership.Level.MEMBER)

    @parameterized.expand([("organization", True), ("all_organizations", False)])
    def test_sdk_project_access_revokes_within_session_and_rolls_back(self, _name: str, scoped: bool) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        create_access_control(
            team_id=self.team.id, resource="project", resource_id=str(self.team.id), access_level="none"
        )
        resource = Resource(type=ResourceType.PROJECT, id=str(self.team.pk), project_id=self.team.pk)
        project_list = Resource(type=ResourceType.PROJECT, organization_id=self.organization.id if scoped else None)
        subject = Subject(user_id=self.user.pk)
        with authorization.authorization_session():
            assert not authorization.list_objects(resource=project_list, action=Action.VIEW, subject=subject).allows(
                str(self.team.pk)
            )
            self.grant()
            assert authorization.check(resource=resource, action=Action.EDIT, subject=subject)
            assert Action.EDIT in authorization.permissions(resource=resource, subject=subject)
            assert authorization.list_objects(resource=project_list, action=Action.VIEW, subject=subject).allows(
                str(self.team.pk)
            )
            with transaction.atomic():
                Role.objects.filter(pk=self.role.pk).update(organization_access_level=None)
                assert not authorization.check(resource=resource, action=Action.EDIT, subject=subject)
                assert Action.EDIT not in authorization.permissions(resource=resource, subject=subject)
                assert not authorization.list_objects(
                    resource=project_list, action=Action.VIEW, subject=subject
                ).allows(str(self.team.pk))
                transaction.set_rollback(True)
            assert authorization.check(resource=resource, action=Action.EDIT, subject=subject)
            assert authorization.list_objects(resource=project_list, action=Action.VIEW, subject=subject).allows(
                str(self.team.pk)
            )

    def test_role_grant_does_not_enable_unsupported_credentials(self) -> None:
        self.grant()
        resource = Resource(type=ResourceType.ORGANIZATION, id=str(self.organization.pk))
        with self.assertRaises(NotImplementedError):
            authorization.check(resource=resource, action=Action.EDIT, subject=Subject(api_key_id="example-key"))

    def test_deployment_does_not_reuse_unannotated_membership_payloads(self) -> None:
        self.grant()
        old_namespace = f"django{django.VERSION[0]}.{django.VERSION[1]}"
        caches["organization_access"].set(
            f"organization_access:membership:{self.organization.id}:{self.user.id}:{old_namespace}",
            (None, self.organization_membership),
        )
        caches["organization_access"].set(
            f"organization_access:user_memberships:{self.user.id}:{old_namespace}",
            (None, [self.organization_membership]),
        )
        self.assert_access(OrganizationMembership.Level.ADMIN)
        with self.assertNumQueries(0):
            self.assert_access(OrganizationMembership.Level.ADMIN)

    @parameterized.expand([("role",), ("membership",)])
    def test_bulk_upsert_cannot_bypass_grant_invalidation(self, model: str) -> None:
        link = self.grant()
        self.assert_access(OrganizationMembership.Level.ADMIN)
        if model == "role":
            self.role.organization_access_level = None
        else:
            link.user = User.objects.create_and_join(self.organization, "upsert@example.com", None)
        with self.assertRaises(ValueError):
            if model == "role":
                Role.objects.bulk_create(
                    [self.role],
                    update_conflicts=True,
                    update_fields=["organization_access_level"],
                    unique_fields=["id"],
                )
            else:
                RoleMembership.objects.bulk_create(
                    [link], update_conflicts=True, update_fields=["user"], unique_fields=["id"]
                )
        self.assert_access(OrganizationMembership.Level.ADMIN)

    @parameterized.expand(
        [("grant", None, OrganizationMembership.Level.ADMIN), ("revoke", OrganizationMembership.Level.ADMIN, None)]
    )
    def test_role_edit_invalidates_members_added_before_commit(
        self, _name: str, before: int | None, after: int | None
    ) -> None:
        self.role.organization_access_level = before
        self.role.save()

        def join_and_warm_cache() -> None:
            try:
                self.grant()
                self.assert_access(before or OrganizationMembership.Level.MEMBER)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                self.role.organization_access_level = after
                self.role.save()
                executor.submit(join_and_warm_cache).result(timeout=60)
            self.assert_access(after or OrganizationMembership.Level.MEMBER)
