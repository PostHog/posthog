import pytest

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership

from products.access_control.backend.tests.test_user_access_control import BaseUserAccessControlTest
from products.dashboards.backend.models.dashboard import Dashboard
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource

# Named specification of the most-specific resolution semantics plus the cases the property-based
# harness (test_user_access_control_pbt.py) cannot generate: the RESOURCE_FALLBACK_MAP ladder,
# resolution without the entitlement, and resources without resource-level controls. Exhaustive
# combination coverage lives in the harness's oracle tests, not here.


class BaseAccessResolutionTest(BaseUserAccessControlTest):
    def setUp(self):
        super().setUp()
        self.membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        self.dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)

    def _apply(self, rules: dict[str, str]) -> None:
        # Each key is one place a dashboard rule can be written; the ladder under test is the
        # precedence between them
        targets = {
            "member": ("dashboard", str(self.dashboard.id), self.membership, None),
            "role_a": ("dashboard", str(self.dashboard.id), None, self.role_a),
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
        return self.user_access_control._resolved_object_access(self.dashboard)


@pytest.mark.ee
class TestResolveObjectAccess(BaseAccessResolutionTest):
    @parameterized.expand(
        [
            # Within the object scope, the member's own row decides even when it grants less
            ("member_deny_beats_role_grant", {"member": "none", "role_a": "editor"}, "none", "object", "member"),
            ("member_grant_beats_role_deny", {"member": "editor", "role_a": "none"}, "editor", "object", "member"),
            (
                "resource_member_grant_beats_role_deny_for_object_default",
                {"resource_member": "viewer", "resource_role_a": "none", "object_default": "manager"},
                "manager",
                "object",
                "default",
            ),
            (
                "object_default_deny_beats_resource_grant",
                {"object_default": "none", "resource_default": "editor"},
                "none",
                "object",
                "default",
            ),
            (
                "resource_deny_gates_object_default_grant",
                {"object_default": "editor", "resource_default": "none"},
                "none",
                "resource",
                "default",
            ),
        ]
    )
    def test_object_ladder(self, _name, rules, expected_level, expected_source, expected_subject):
        self._apply(rules)

        resolved = self._resolve()

        assert resolved is not None
        assert resolved.access_level == expected_level
        assert resolved.source == expected_source
        assert resolved.source_subject == expected_subject

    @parameterized.expand(
        [
            (resource_subject, resource_level, object_level, sharing)
            for resource_subject in ("resource_member", "resource_role_a", "resource_default")
            for resource_level, object_level, sharing in (
                ("none", "viewer", None),
                ("none", "manager", None),
                ("viewer", "editor", None),
                ("viewer", "manager", None),
                ("editor", "viewer", None),
                ("viewer", "none", None),
                ("none", "manager", "member"),
                ("none", "manager", "role_a"),
            )
        ]
    )
    def test_resource_gate_preserves_explicit_sharing(
        self, resource_subject: str, resource_level: str, object_level: str, sharing: str | None
    ) -> None:
        rules = {resource_subject: resource_level, "object_default": object_level}
        if sharing:
            rules[sharing] = "viewer"
        self._apply(rules)
        expected = "viewer" if sharing else "none" if resource_level == "none" else object_level
        uac = self.user_access_control

        assert uac.get_user_access_level(self.dashboard) == expected
        assert uac.bulk_object_access_levels("dashboard", [(str(self.dashboard.id), self.dashboard.created_by_id)]) == {
            str(self.dashboard.id): expected
        }
        assert uac.filter_queryset_by_access_level(Dashboard.objects.filter(pk=self.dashboard.pk)).exists() == (
            expected != "none"
        )

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
class TestResolveObjectAccessFallbackParent(BaseAccessResolutionTest):
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
            (
                "table_default_respects_resource_deny",
                {"this_table_default": "editor", "resource_member": "none"},
                "none",
                "resource",
            ),
            (
                "source_default_respects_resource_deny",
                {"this_source": "editor", "resource_member": "none"},
                "none",
                "resource",
            ),
            (
                "source_member_grant_overrides_resource_deny",
                {"this_source_member": "viewer", "resource_member": "none"},
                "viewer",
                "parent_object",
            ),
            # The table's own default row is nearer than the source, so it wins
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
            "this_source_member": ("external_data_source", str(self.source.id), self.membership),
            "resource_member": ("warehouse_objects", None, self.membership),
        }
        for target, level in rules.items():
            resource, resource_id, member = targets[target]
            self._create_access_control(
                resource=resource, resource_id=resource_id, access_level=level, organization_member=member
            )
        self._clear_uac_caches()

        resolved = self.user_access_control._resolved_object_access(self.table)

        assert resolved is not None
        assert resolved.access_level == expected_level
        assert resolved.source == expected_source


@pytest.mark.ee
class TestResolveResourceAccess(BaseAccessResolutionTest):
    def test_resource_without_resource_level_controls_resolves_to_system_default(self):
        resolved = self.user_access_control.access_level_for_resource("project")

        assert resolved is not None
        assert resolved.source == "system_default"
        assert resolved.access_level == "admin"
