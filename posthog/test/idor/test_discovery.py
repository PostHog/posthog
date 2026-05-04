"""Unit tests for discovery helpers (pure logic; no Django bootstrap)."""

from __future__ import annotations

import unittest

from rest_framework import serializers, viewsets

from posthog.test.idor.discovery import (
    IDORTestCase,
    _model_has_lookup_attr,
    _should_replace,
    iter_serializer_classes_for,
)
from posthog.test.idor.url_structure import URLStructure


class _FakeModel:
    __name__ = "FakeModel"


class _FakeViewSet:
    __name__ = "FakeViewSet"


def _case(root: str, intermediate_count: int = 0) -> IDORTestCase:
    intermediate = [(f"parent_{i}", f"parent_lookup_{i}_id") for i in range(intermediate_count)]
    return IDORTestCase(
        viewset_cls=_FakeViewSet,
        model_cls=_FakeModel,  # type: ignore[arg-type]
        url=URLStructure(
            root=root,
            root_kwarg=f"parent_lookup_{root}_id",
            resource_prefix="thing",
            pk_kwarg="pk",
            intermediate_parents=intermediate,
        ),
    )


class TestShouldReplace(unittest.TestCase):
    def test_environments_preferred_over_projects(self) -> None:
        existing = _case("projects")
        candidate = _case("environments")
        assert _should_replace(existing, candidate) is True

    def test_projects_not_replaced_by_organizations(self) -> None:
        existing = _case("projects")
        candidate = _case("organizations")
        assert _should_replace(existing, candidate) is False

    def test_shorter_path_preferred_for_same_root(self) -> None:
        existing = _case("environments", intermediate_count=1)
        candidate = _case("environments", intermediate_count=0)
        assert _should_replace(existing, candidate) is True

    def test_longer_path_not_preferred_for_same_root(self) -> None:
        existing = _case("environments", intermediate_count=0)
        candidate = _case("environments", intermediate_count=1)
        assert _should_replace(existing, candidate) is False


class TestModelHasLookupAttr(unittest.TestCase):
    """Joined-attribute resolution (e.g. `user__uuid` on OrganizationMembership)."""

    def test_pk_and_id_always_pass(self) -> None:
        from posthog.models.organization import OrganizationMembership

        assert _model_has_lookup_attr(OrganizationMembership, "pk") is True
        assert _model_has_lookup_attr(OrganizationMembership, "id") is True

    def test_top_level_field(self) -> None:
        from posthog.models.organization import OrganizationMembership

        assert _model_has_lookup_attr(OrganizationMembership, "user") is True

    def test_joined_fk_attribute_resolves(self) -> None:
        from posthog.models.organization import OrganizationMembership

        # `user` is an FK to User; User has a `uuid` field. Should resolve.
        assert _model_has_lookup_attr(OrganizationMembership, "user__uuid") is True

    def test_joined_unknown_terminal_segment_rejects(self) -> None:
        from posthog.models.organization import OrganizationMembership

        assert _model_has_lookup_attr(OrganizationMembership, "user__nonexistent") is False

    def test_joined_unknown_first_segment_rejects(self) -> None:
        from posthog.models.organization import OrganizationMembership

        assert _model_has_lookup_attr(OrganizationMembership, "nonexistent__uuid") is False


class _ReadSerializer(serializers.Serializer):
    name = serializers.CharField()


class _WriteSerializer(serializers.Serializer):
    linked_id = serializers.IntegerField()


class _StaticViewSet(viewsets.GenericViewSet):
    serializer_class = _ReadSerializer


class _DispatchingViewSet(viewsets.GenericViewSet):
    """Mirrors the SurveyViewSet pattern: read vs write serializers."""

    def get_serializer_class(self):
        if self.request.method in ("POST", "PATCH"):
            return _WriteSerializer
        return _ReadSerializer


class _EmptyViewSet(viewsets.GenericViewSet):
    """No serializer declared at all."""


class _BrokenDispatchingViewSet(viewsets.GenericViewSet):
    """get_serializer_class raises — the probe must swallow it."""

    serializer_class = _ReadSerializer

    def get_serializer_class(self):
        raise RuntimeError("intentional probe failure")


class TestIterSerializerClassesFor(unittest.TestCase):
    def test_static_serializer_class_returned(self) -> None:
        result = iter_serializer_classes_for(_StaticViewSet)
        assert result == [_ReadSerializer]

    def test_dispatching_viewset_yields_both_serializers(self) -> None:
        result = iter_serializer_classes_for(_DispatchingViewSet)
        # No class-level serializer_class; probe yields the runtime ones.
        assert _WriteSerializer in result, f"write serializer missing from {result}"
        assert _ReadSerializer in result, f"read serializer missing from {result}"

    def test_empty_viewset_returns_empty_list(self) -> None:
        result = iter_serializer_classes_for(_EmptyViewSet)
        assert result == []

    def test_broken_dispatch_falls_back_to_static(self) -> None:
        # The override raises every time, but the static class-level fallback
        # must still be returned so discovery isn't blocked.
        result = iter_serializer_classes_for(_BrokenDispatchingViewSet)
        assert result == [_ReadSerializer]

    def test_result_is_deduplicated(self) -> None:
        result = iter_serializer_classes_for(_StaticViewSet)
        assert len(result) == len(set(result))


if __name__ == "__main__":
    unittest.main()
