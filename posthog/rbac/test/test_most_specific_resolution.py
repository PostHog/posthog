import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership
from posthog.rbac.subject_access_control import SubjectAccessControl
from posthog.rbac.test.test_user_access_control import BaseUserAccessControlTest

from products.dashboards.backend.models.dashboard import Dashboard
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource

try:
    from ee.models.rbac.role import RoleMembership
except ImportError:
    pass


class BaseMostSpecificResolutionTest(BaseUserAccessControlTest):
    def setUp(self):
        super().setUp()
        self.membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        self.other_membership = OrganizationMembership.objects.get(user=self.other_user, organization=self.organization)
        self.dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)

    def _apply(self, rules: dict[str, str]) -> None:
        # Each key is one place a dashboard rule can be written; the ladder under test is the
        # precedence between them
        targets = {
            "member": ("dashboard", str(self.dashboard.id), self.membership, None),
            "other_member": ("dashboard", str(self.dashboard.id), self.other_membership, None),
            "role_a": ("dashboard", str(self.dashboard.id), None, self.role_a),
            "role_b": ("dashboard", str(self.dashboard.id), None, self.role_b),
            "object_default": ("dashboard", str(self.dashboard.id), None, None),
            "resource_member": ("dashboard", None, self.membership, None),
            "resource_role_a": ("dashboard", None, None, self.role_a),
            "resource_default": ("dashboard", None, None, None),
        }
        for target, level in rules.items():
            resource, resource_id, member, role = targets[target]
            self._create_access_control(
                resource=resource, resource_id=resource_id, access_level=level, organization_member=member, role=role
            )
        self._clear_uac_caches()

    def _resolve(self):
        return self.user_access_control.resolve_object_access(self.dashboard)


@pytest.mark.ee
class TestResolveObjectAccess(BaseMostSpecificResolutionTest):
    @parameterized.expand(
        [
            # Within the object scope, the member's own row decides even when it grants less
            ("member_deny_beats_role_grant", {"member": "none", "role_a": "editor"}, "none", "object", "member"),
            ("member_grant_beats_role_deny", {"member": "editor", "role_a": "none"}, "editor", "object", "member"),
            # The object's default row is more specific than any resource-wide rule, both directions
            (
                "object_default_deny_beats_resource_grant",
                {"object_default": "none", "resource_default": "editor"},
                "none",
                "object",
                "default",
            ),
            (
                "object_default_grant_beats_resource_deny",
                {"object_default": "editor", "resource_default": "none"},
                "editor",
                "object",
                "default",
            ),
            # With no object rows the resource scope decides, by the same subject ladder
            ("resource_applies_without_object_rows", {"resource_default": "viewer"}, "viewer", "resource", "default"),
            (
                "resource_member_deny_beats_resource_role_grant",
                {"resource_member": "none", "resource_role_a": "editor"},
                "none",
                "resource",
                "member",
            ),
            # Rows about other people are invisible to this user's resolution
            ("other_member_row_is_invisible", {"other_member": "none"}, "editor", "system_default", None),
            ("no_rules_resolves_to_system_default", {}, "editor", "system_default", None),
        ]
    )
    def test_object_ladder(self, _name, rules, expected_level, expected_source, expected_subject):
        self._apply(rules)

        resolved = self._resolve()

        assert resolved is not None
        assert resolved.access_level == expected_level
        assert resolved.source == expected_source
        assert resolved.source_subject == expected_subject

    def test_roles_still_combine_by_max_within_the_role_tier(self):
        RoleMembership.objects.create(user=self.user, role=self.role_b)
        self._apply({"role_a": "none", "role_b": "viewer"})

        resolved = self._resolve()

        assert resolved is not None
        assert resolved.access_level == "viewer"
        assert resolved.source_subject == "role"

    def test_creator_bypasses_all_rules(self):
        self._apply({"object_default": "none"})
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)

        resolved = self.user_access_control.resolve_object_access(dashboard)

        assert resolved is not None
        assert resolved.access_level == "manager"
        assert resolved.source == "creator"

    def test_org_admin_bypasses_all_rules(self):
        self._apply({"member": "none"})
        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()
        self._clear_uac_caches()

        resolved = self._resolve()

        assert resolved is not None
        assert resolved.access_level == "manager"
        assert resolved.source == "org_admin"

    @parameterized.expand(
        [
            ("no_rules", {}),
            ("object_default_rule", {"object_default": "viewer"}),
            ("resource_rule", {"resource_default": "viewer"}),
        ]
    )
    def test_source_system_default_is_equivalent_to_legacy_explicit_true(self, _name, rules):
        # The new resolvers have no `explicit` parameter. On the enforced method, explicit=True
        # returns None exactly when the new answer has source="system_default". The future
        # adapter in get_user_access_level relies on this equivalence.
        self._apply(rules)

        legacy_explicit = self.user_access_control.get_user_access_level(self.dashboard, explicit=True)
        resolved = self._resolve()

        assert resolved is not None
        assert (legacy_explicit is None) == (resolved.source == "system_default")

    def test_no_entitlement_resolves_to_system_default(self):
        self._apply({"member": "none"})
        self.organization.available_product_features = []
        self.organization.save()
        self._clear_uac_caches()

        resolved = self._resolve()

        assert resolved is not None
        assert resolved.access_level == "editor"
        assert resolved.source == "system_default"


@pytest.mark.ee
class TestResolveObjectAccessFallbackParent(BaseMostSpecificResolutionTest):
    def setUp(self):
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id="src",
            connection_id="conn",
            destination_id="dest",
            source_type="Stripe",
            prefix="test",
        )
        self.table = DataWarehouseTable.objects.create(
            name="customers", format="Parquet", team=self.team, external_data_source=self.source, columns={}
        )

    @parameterized.expand(
        [
            # A rule about the source reaches the tables it syncs
            ("source_deny_reaches_the_table", {"this_source": "none"}, "none", "parent_object"),
            # The table's own default row is nearer than the source, so it wins — under the
            # enforced ladder the source's row would win here
            (
                "table_default_beats_source_deny",
                {"this_table_default": "editor", "this_source": "none"},
                "editor",
                "object",
            ),
            (
                "member_on_table_beats_everything",
                {"this_table_member": "viewer", "this_source": "none"},
                "viewer",
                "object",
            ),
        ]
    )
    def test_fallback_parent_ladder(self, _name, rules, expected_level, expected_source):
        targets = {
            "this_table_member": ("warehouse_table", str(self.table.id), self.membership),
            "this_table_default": ("warehouse_table", str(self.table.id), None),
            "this_source": ("external_data_source", str(self.source.id), None),
        }
        for target, level in rules.items():
            resource, resource_id, member = targets[target]
            self._create_access_control(
                resource=resource, resource_id=resource_id, access_level=level, organization_member=member
            )
        self._clear_uac_caches()

        resolved = self.user_access_control.resolve_object_access(self.table)

        assert resolved is not None
        assert resolved.access_level == expected_level
        assert resolved.source == expected_source


@pytest.mark.ee
class TestResolveResourceAccess(BaseMostSpecificResolutionTest):
    @parameterized.expand(
        [
            (
                "member_deny_beats_role_grant",
                {"resource_member": "none", "resource_role_a": "editor"},
                "none",
                "member",
            ),
            (
                "member_grant_beats_role_deny",
                {"resource_member": "editor", "resource_role_a": "none"},
                "editor",
                "member",
            ),
            ("role_applies_without_member_row", {"resource_role_a": "viewer"}, "viewer", "role"),
            ("default_row_applies_without_overrides", {"resource_default": "none"}, "none", "default"),
        ]
    )
    def test_resource_ladder(self, _name, rules, expected_level, expected_subject):
        self._apply(rules)

        resolved = self.user_access_control.resolve_resource_access("dashboard")

        assert resolved is not None
        assert resolved.access_level == expected_level
        assert resolved.source == "resource"
        assert resolved.source_subject == expected_subject

    def test_no_rows_resolves_to_system_default(self):
        resolved = self.user_access_control.resolve_resource_access("dashboard")

        assert resolved is not None
        assert resolved.access_level == "editor"
        assert resolved.source == "system_default"

    def test_org_admin_bypasses_rows(self):
        self._apply({"resource_member": "none"})
        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()
        self._clear_uac_caches()

        resolved = self.user_access_control.resolve_resource_access("dashboard")

        assert resolved is not None
        assert resolved.access_level == "manager"
        assert resolved.source == "org_admin"

    def test_inheriting_resource_resolves_through_its_umbrella(self):
        self._create_access_control(
            resource="warehouse_objects", resource_id=None, access_level="none", organization_member=self.membership
        )
        self._clear_uac_caches()

        resolved = self.user_access_control.resolve_resource_access("warehouse_table")

        assert resolved is not None
        assert resolved.access_level == "none"
        assert resolved.source_resource == "warehouse_objects"

    def test_resource_without_resource_level_controls_resolves_to_system_default(self):
        resolved = self.user_access_control.resolve_resource_access("project")

        assert resolved is not None
        assert resolved.source == "system_default"
        assert resolved.access_level == "admin"


@pytest.mark.ee
class TestShadowDivergenceTelemetry(BaseMostSpecificResolutionTest):
    @patch("posthog.rbac.user_access_control.posthoganalytics.capture")
    def test_enforcement_keeps_the_legacy_answer_and_reports_the_divergence(self, mock_capture):
        self._apply({"member": "none", "role_a": "editor"})

        level = self.user_access_control.get_user_access_level(self.dashboard)

        # Legacy max() still enforced: the role grant wins today, and the event records that the
        # future answer differs
        assert level == "editor"
        assert mock_capture.call_count == 1
        properties = mock_capture.call_args.kwargs["properties"]
        assert properties["kind"] == "object"
        assert properties["resource"] == "dashboard"
        assert properties["direction"] == "narrows"
        assert properties["current_level"] == "editor"
        assert properties["proposed_level"] == "none"
        assert properties["proposed_source_subject"] == "member"

    @patch("posthog.rbac.user_access_control.posthoganalytics.capture")
    def test_divergence_is_reported_once_per_instance(self, mock_capture):
        self._apply({"member": "none", "role_a": "editor"})

        self.user_access_control.get_user_access_level(self.dashboard)
        self.user_access_control.get_user_access_level(self.dashboard)

        assert mock_capture.call_count == 1

    @patch("posthog.rbac.user_access_control.posthoganalytics.capture")
    def test_no_event_when_resolutions_agree(self, mock_capture):
        self._apply({"member": "editor", "role_a": "viewer"})

        assert self.user_access_control.get_user_access_level(self.dashboard) == "editor"
        assert mock_capture.call_count == 0

    @patch("posthog.rbac.user_access_control.posthoganalytics.capture")
    def test_resource_divergence_is_reported(self, mock_capture):
        self._apply({"resource_member": "none", "resource_role_a": "editor"})

        access = self.user_access_control.access_level_for_resource("dashboard")

        assert access is not None
        assert access.access_level == "editor"
        assert mock_capture.call_count == 1
        properties = mock_capture.call_args.kwargs["properties"]
        assert properties["kind"] == "resource"
        assert properties["proposed_level"] == "none"

    @patch("posthog.rbac.user_access_control.posthoganalytics.capture")
    def test_subject_resolution_does_not_report(self, mock_capture):
        # SubjectAccessControl resolves other people's access for display; its divergences are
        # about the subject, not the requesting user, so the shadow skips subclasses entirely
        self._apply({"member": "none", "role_a": "editor"})
        subject = SubjectAccessControl.for_member(self.user_access_control, self.team, self.membership)

        subject.get_user_access_level(self.dashboard)

        assert mock_capture.call_count == 0
