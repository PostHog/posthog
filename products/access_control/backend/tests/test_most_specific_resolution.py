import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership

from products.access_control.backend.facade.subject_access_control import SubjectAccessControl
from products.access_control.backend.tests.test_user_access_control import BaseUserAccessControlTest
from products.dashboards.backend.models.dashboard import Dashboard
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource

# Named specification of the most-specific resolution semantics plus the cases the property-based
# harness (test_user_access_control_pbt.py) cannot generate: the RESOURCE_FALLBACK_MAP ladder,
# resolution without the entitlement, resources without resource-level controls, and the
# shadow-divergence telemetry. Exhaustive combination coverage lives in the harness's
# most-specific oracle tests, not here.


class BaseMostSpecificResolutionTest(BaseUserAccessControlTest):
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
        return self.user_access_control.resolve_most_specific_object_access(self.dashboard)


@pytest.mark.ee
class TestResolveObjectAccess(BaseMostSpecificResolutionTest):
    @parameterized.expand(
        [
            # Within the object scope, the member's own row decides even when it grants less
            ("member_deny_beats_role_grant", {"member": "none", "role_a": "editor"}, "none", "object", "member"),
            ("member_grant_beats_role_deny", {"member": "editor", "role_a": "none"}, "editor", "object", "member"),
            # The object's own default row is more specific than any resource-wide rule
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
        ]
    )
    def test_object_ladder(self, _name, rules, expected_level, expected_source, expected_subject):
        self._apply(rules)

        resolved = self._resolve()

        assert resolved is not None
        assert resolved.access_level == expected_level
        assert resolved.source == expected_source
        assert resolved.source_subject == expected_subject

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

        resolved = self.user_access_control.resolve_most_specific_object_access(self.table)

        assert resolved is not None
        assert resolved.access_level == expected_level
        assert resolved.source == expected_source


@pytest.mark.ee
class TestResolveResourceAccess(BaseMostSpecificResolutionTest):
    def test_resource_without_resource_level_controls_resolves_to_system_default(self):
        resolved = self.user_access_control.resolve_most_specific_resource_access("project")

        assert resolved is not None
        assert resolved.source == "system_default"
        assert resolved.access_level == "admin"


@pytest.mark.ee
class TestShadowDivergenceTelemetry(BaseMostSpecificResolutionTest):
    @patch("products.access_control.backend.facade.user_access_control.posthoganalytics.capture")
    def test_enforcement_keeps_the_enforced_answer_and_reports_the_divergence(self, mock_capture):
        self._apply({"member": "none", "role_a": "editor"})

        level = self.user_access_control.get_user_access_level(self.dashboard)

        # The enforced max() still decides: the role grant wins today, and the event records that
        # the future answer differs
        assert level == "editor"
        assert mock_capture.call_count == 1
        properties = mock_capture.call_args.kwargs["properties"]
        assert properties["kind"] == "object"
        assert properties["resource"] == "dashboard"
        assert properties["direction"] == "narrows"
        assert properties["current_level"] == "editor"
        assert properties["proposed_level"] == "none"
        assert properties["proposed_source_subject"] == "member"

    @patch("products.access_control.backend.facade.user_access_control.posthoganalytics.capture")
    def test_divergence_is_reported_once_per_instance(self, mock_capture):
        self._apply({"member": "none", "role_a": "editor"})

        self.user_access_control.get_user_access_level(self.dashboard)
        self.user_access_control.get_user_access_level(self.dashboard)

        assert mock_capture.call_count == 1

    @patch("products.access_control.backend.facade.user_access_control.posthoganalytics.capture")
    def test_no_event_when_resolutions_agree(self, mock_capture):
        self._apply({"member": "editor", "role_a": "viewer"})

        assert self.user_access_control.get_user_access_level(self.dashboard) == "editor"
        assert mock_capture.call_count == 0

    @patch("products.access_control.backend.facade.user_access_control.posthoganalytics.capture")
    def test_resource_divergence_is_reported(self, mock_capture):
        self._apply({"resource_member": "none", "resource_role_a": "editor"})

        access = self.user_access_control.access_level_for_resource("dashboard")

        assert access is not None
        assert access.access_level == "editor"
        assert mock_capture.call_count == 1
        properties = mock_capture.call_args.kwargs["properties"]
        assert properties["kind"] == "resource"
        assert properties["proposed_level"] == "none"

    @patch("products.access_control.backend.facade.user_access_control.posthoganalytics.capture")
    def test_subject_resolution_does_not_report(self, mock_capture):
        # SubjectAccessControl resolves other people's access for display; its divergences are
        # about the subject, not the requesting user, so the shadow skips subclasses entirely
        self._apply({"member": "none", "role_a": "editor"})
        subject = SubjectAccessControl.for_member(self.user_access_control, self.team, self.membership)

        subject.get_user_access_level(self.dashboard)

        assert mock_capture.call_count == 0
