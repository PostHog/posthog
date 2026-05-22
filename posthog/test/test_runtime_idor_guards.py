"""
Tests for the runtime IDOR guards installed by posthog.conftest.

These tests exercise the autouse fixture ``enforce_detail_object_permissions``
by constructing scenarios that the guard is supposed to catch, and asserting
that an AssertionError is raised.
"""

from typing import Any

import pytest
from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Annotation, Organization, Team

from products.dashboards.backend.models.dashboard import Dashboard


class TestCrossTenantFKGuard(APIBaseTest):
    def _other_team_dashboard(self) -> Dashboard:
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        return Dashboard.objects.create(team=other_team, name="foreign dashboard")

    def test_guard_catches_cross_tenant_dashboard_id_on_annotation_create(self):
        """
        Reproduces the PR 45196 IDOR pattern. The current AnnotationSerializer
        rejects cross-tenant dashboard_id in validate(). To prove the guard
        catches the pre-fix vulnerability, we monkeypatch the validate method
        to drop that check, then attempt the write — the runtime guard should
        catch the cross-tenant FK as save() lands.
        """
        from posthog.api import annotation as annotation_module

        other_dashboard = self._other_team_dashboard()

        original_validate = annotation_module.AnnotationSerializer.validate

        def neutered_validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
            return attrs

        annotation_module.AnnotationSerializer.validate = neutered_validate  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
        try:
            with pytest.raises(AssertionError, match="Cross-tenant FK IDOR"):
                self.client.post(
                    f"/api/projects/{self.team.id}/annotations/",
                    {"content": "x", "dashboard_id": other_dashboard.id, "scope": Annotation.Scope.DASHBOARD.value},
                    format="json",
                )
        finally:
            annotation_module.AnnotationSerializer.validate = original_validate  # type: ignore[method-assign]

    def test_guard_allows_same_tenant_dashboard_id_on_annotation_create(self):
        own_dashboard = Dashboard.objects.create(team=self.team, name="own dashboard")
        response = self.client.post(
            f"/api/projects/{self.team.id}/annotations/",
            {"content": "x", "dashboard_id": own_dashboard.id, "scope": Annotation.Scope.DASHBOARD.value},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

    @pytest.mark.skip_access_control_permission_check
    def test_marker_disables_guard(self):
        """
        Opt-out marker must short-circuit the guard. If it does not, the
        neutered serializer would raise. With the marker, no AssertionError.
        """
        from posthog.api import annotation as annotation_module

        other_dashboard = self._other_team_dashboard()
        original_validate = annotation_module.AnnotationSerializer.validate

        def passthrough_validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
            return attrs

        annotation_module.AnnotationSerializer.validate = passthrough_validate  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
        try:
            # Should not raise AssertionError from the guard; the API may still
            # respond with whatever status — we only care that the guard does
            # not fire.
            self.client.post(
                f"/api/projects/{self.team.id}/annotations/",
                {"content": "x", "dashboard_id": other_dashboard.id, "scope": Annotation.Scope.DASHBOARD.value},
                format="json",
            )
        finally:
            annotation_module.AnnotationSerializer.validate = original_validate  # type: ignore[method-assign]
