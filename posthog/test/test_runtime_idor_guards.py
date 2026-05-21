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


class TestMassAssignmentGuard(APIBaseTest):
    def test_guard_catches_writable_team_id_even_when_request_does_not_set_it(self):
        """
        The guard's triggering condition is "serializer used for input
        validation"; the assertion is on declared shape. So a request that
        only updates an unrelated field must still fail if the serializer
        also exposes team_id (or another tenancy boundary) as writable.

        We monkey-patch AnnotationSerializer's Meta to drop dashboard_id from
        read_only_fields and expose team_id as writable. A PATCH that only
        touches the ``content`` field must then trigger the mass-assignment
        guard solely on the shape of the serializer.
        """
        from rest_framework import serializers as drf_serializers

        from posthog.api import annotation as annotation_module

        annotation = Annotation.objects.create(team=self.team, content="original", scope=Annotation.Scope.PROJECT.value)

        # Save originals to restore later.
        original_fields = annotation_module.AnnotationSerializer.Meta.fields
        original_read_only = getattr(annotation_module.AnnotationSerializer.Meta, "read_only_fields", None)

        # Override Meta to include team_id as writable.
        new_fields = [*list(original_fields), "team_id"]
        annotation_module.AnnotationSerializer.Meta.fields = new_fields
        # Wipe the cached _declared_fields so DRF rebuilds them on next instance.
        if hasattr(annotation_module.AnnotationSerializer, "_declared_fields"):
            # Add explicit team_id IntegerField (so it survives __all__-style resolution)
            annotation_module.AnnotationSerializer._declared_fields["team_id"] = drf_serializers.IntegerField(
                required=False
            )

        try:
            with pytest.raises(AssertionError, match="Mass-assignment IDOR risk"):
                self.client.patch(
                    f"/api/projects/{self.team.id}/annotations/{annotation.id}/",
                    {"content": "updated"},
                    format="json",
                )
        finally:
            annotation_module.AnnotationSerializer.Meta.fields = original_fields
            if original_read_only is not None:
                annotation_module.AnnotationSerializer.Meta.read_only_fields = original_read_only
            annotation_module.AnnotationSerializer._declared_fields.pop("team_id", None)

    def test_guard_does_not_fire_on_clean_serializer(self):
        """A plain PATCH that only updates ``content`` on the unmodified
        AnnotationSerializer (which does not expose tenancy fields as writable)
        must not trigger the mass-assignment guard.
        """
        annotation = Annotation.objects.create(team=self.team, content="original", scope=Annotation.Scope.PROJECT.value)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/annotations/{annotation.id}/",
            {"content": "updated"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
