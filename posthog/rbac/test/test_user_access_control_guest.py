"""Tests for the guest-mode inversion baked into UserAccessControl.

`OrganizationMembership.is_guest=True` flips the AC layer's default from "allow" to "deny":
regular members get `default_access_level(resource)` when no AC row matches; guests get
`NO_ACCESS_LEVEL` instead. Access for guests is granted only by explicit AccessControl rows.
"""

import pytest
from posthog.test.base import BaseTest

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.rbac.user_access_control import NO_ACCESS_LEVEL, UserAccessControl

from products.dashboards.backend.models.dashboard import Dashboard

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


@pytest.mark.ee
class TestUserAccessControlGuestInversion(BaseTest):
    """Verifies the single-branch inversion at the three AC entry points."""

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
        ]
        self.organization.save()

        # Regular (non-guest) baseline user: default permissions apply.
        self.regular_user = User.objects.create_and_join(self.organization, "regular@posthog.com", "testtest")
        self.regular_membership = OrganizationMembership.objects.get(
            organization=self.organization, user=self.regular_user
        )
        self.regular_uac = UserAccessControl(self.regular_user, self.team)

        # Guest user.
        self.guest_user = User.objects.create_user(email="guest@posthog.com", first_name="G", password="testtest")
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )
        self.guest_uac = UserAccessControl(self.guest_user, self.team)

        # Two dashboards used across tests.
        self.granted_dashboard = Dashboard.objects.create(team=self.team, name="Granted")
        self.other_dashboard = Dashboard.objects.create(team=self.team, name="Other")

    def _clear_caches(self) -> None:
        self.regular_uac._clear_cache()
        self.guest_uac._clear_cache()

    # ------------------------------------------------------------
    # Baseline: regular members are unaffected by the inversion.
    # ------------------------------------------------------------

    def test_regular_member_without_ac_row_has_default_access(self) -> None:
        """Regression guard: regular members still receive `default_access_level` when no AC row exists."""
        # default for dashboards is `editor`.
        self.assertEqual(self.regular_uac.access_level_for_object(self.granted_dashboard), "editor")
        self.assertEqual(self.regular_uac.access_level_for_resource("dashboard"), "editor")

    # ------------------------------------------------------------
    # Guest without AC row: denied.
    # ------------------------------------------------------------

    def test_guest_without_ac_row_returns_none_for_object(self) -> None:
        self.assertEqual(self.guest_uac.access_level_for_object(self.granted_dashboard), NO_ACCESS_LEVEL)

    def test_guest_without_ac_row_returns_none_for_resource(self) -> None:
        self.assertEqual(self.guest_uac.access_level_for_resource("dashboard"), NO_ACCESS_LEVEL)

    def test_guest_without_ac_row_returns_none_for_object_with_explicit_flag(self) -> None:
        """When callers pass `explicit=True`, the inversion returns None (no explicit row exists)."""
        self.assertIsNone(self.guest_uac.access_level_for_object(self.granted_dashboard, explicit=True))

    # ------------------------------------------------------------
    # Guest with specific AC row: allowed at the granted level.
    # ------------------------------------------------------------

    def test_guest_with_viewer_ac_row_gets_viewer_on_that_object(self) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(self.granted_dashboard.pk),
            organization_member=self.guest_membership,
            access_level="viewer",
        )
        self._clear_caches()
        self.assertEqual(self.guest_uac.access_level_for_object(self.granted_dashboard), "viewer")
        # Unrelated dashboard still denied.
        self.assertEqual(self.guest_uac.access_level_for_object(self.other_dashboard), NO_ACCESS_LEVEL)

    def test_guest_with_editor_ac_row_gets_editor_on_that_object(self) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(self.granted_dashboard.pk),
            organization_member=self.guest_membership,
            access_level="editor",
        )
        self._clear_caches()
        self.assertEqual(self.guest_uac.access_level_for_object(self.granted_dashboard), "editor")

    # ------------------------------------------------------------
    # Queryset filtering: guest sees only explicitly-granted rows.
    # ------------------------------------------------------------

    def test_filter_queryset_returns_only_granted_dashboards_for_guest(self) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(self.granted_dashboard.pk),
            organization_member=self.guest_membership,
            access_level="viewer",
        )
        self._clear_caches()
        dashboards = Dashboard.objects.filter(team=self.team)
        filtered = self.guest_uac.filter_queryset_by_access_level(dashboards)
        ids = set(filtered.values_list("id", flat=True))
        self.assertIn(self.granted_dashboard.id, ids)
        self.assertNotIn(self.other_dashboard.id, ids)

    def test_filter_queryset_access_level_for_guest_denies_ungranted_on_resource_check(self) -> None:
        """Per-object access for an ungranted dashboard resolves to `none` for a guest.

        `filter_queryset_by_access_level` narrows the queryset to allowed_resource_ids only
        when at least one explicit AC row exists on the resource type; without any row at all
        the function is a no-op and downstream viewset/middleware checks are expected to
        enforce the block (documented at ~line 878 of user_access_control.py). This test
        pins that per-object `access_level_for_object` still reports `none` on untouched
        dashboards, which is what the viewset-level permission check relies on.
        """
        self._clear_caches()
        self.assertEqual(self.guest_uac.access_level_for_object(self.granted_dashboard), NO_ACCESS_LEVEL)
        self.assertEqual(self.guest_uac.access_level_for_object(self.other_dashboard), NO_ACCESS_LEVEL)

    # ------------------------------------------------------------
    # Regular member with AC row at a specific level is unchanged.
    # ------------------------------------------------------------

    def test_regular_member_with_specific_ac_row_unchanged(self) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(self.granted_dashboard.pk),
            organization_member=self.regular_membership,
            access_level="viewer",
        )
        self._clear_caches()
        self.assertEqual(self.regular_uac.access_level_for_object(self.granted_dashboard), "viewer")
        # Another dashboard without an AC row still falls back to the default level.
        self.assertEqual(self.regular_uac.access_level_for_object(self.other_dashboard), "editor")
