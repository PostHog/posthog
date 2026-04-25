"""
Canary for the writable-FK PATCH detection.

`test_canary.py` covers the cross-team GET/PATCH/DELETE assertions; this
file separately proves the FK-discovery layer surfaces a vulnerable FK
field correctly. If `discover_writable_tenant_fks` ever silently stops
flagging an unscoped tenant FK, every entry in
`test_cross_tenant_fk_in_patch` becomes a no-op while the suite still
shows green — exactly the failure mode this canary catches.
"""

from __future__ import annotations

import unittest

from rest_framework import serializers

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.insight import Insight
from posthog.test.idor.fk_discovery import discover_writable_tenant_fks


class _VulnerableFakeSerializer(serializers.ModelSerializer):
    """Deliberately-vulnerable serializer: unscoped FeatureFlag PK field."""

    feature_flag = serializers.PrimaryKeyRelatedField(queryset=FeatureFlag.objects.all())

    class Meta:
        model = Insight
        fields = ["id", "name", "feature_flag"]


class _SafeFakeSerializer(serializers.ModelSerializer):
    """Safe baseline: same FK but scoped via TeamScopedPrimaryKeyRelatedField."""

    feature_flag = TeamScopedPrimaryKeyRelatedField(queryset=FeatureFlag.objects.all())

    class Meta:
        model = Insight
        fields = ["id", "name", "feature_flag"]


class TestFKDiscoveryCanary(unittest.TestCase):
    def test_vulnerable_serializer_is_flagged(self) -> None:
        result = discover_writable_tenant_fks(_VulnerableFakeSerializer)
        assert len(result) == 1, "discovery should flag exactly one writable tenant FK"
        fk = result[0]
        assert fk.serializer_field_name == "feature_flag"
        assert fk.target_model is FeatureFlag
        assert fk.scope == "team"
        assert fk.is_already_scoped is False, "canary failed: discovery marked an UNSCOPED PK field as already_scoped"

    def test_scoped_serializer_marked_already_scoped(self) -> None:
        result = discover_writable_tenant_fks(_SafeFakeSerializer)
        assert len(result) == 1
        assert result[0].is_already_scoped is True, (
            "canary failed: discovery did not recognize TeamScopedPrimaryKeyRelatedField as scoped"
        )

    def test_discovery_returns_empty_for_no_fks(self) -> None:
        class _NoFKsSerializer(serializers.ModelSerializer):
            class Meta:
                model = Insight
                fields = ["id", "name"]

        assert discover_writable_tenant_fks(_NoFKsSerializer) == []

    def test_implicit_id_pattern_is_flagged(self) -> None:
        """Canary for the `<thing>_id = IntegerField()` shape — must surface as `is_implicit=True`."""
        from posthog.models.annotation import Annotation

        from products.dashboards.backend.models.dashboard import Dashboard

        class _ImplicitIdSerializer(serializers.ModelSerializer):
            dashboard_id = serializers.IntegerField(required=False, allow_null=True)

            class Meta:
                model = Annotation
                fields = ["id", "dashboard_id"]

        result = discover_writable_tenant_fks(_ImplicitIdSerializer)
        assert len(result) == 1, "canary failed: implicit `<thing>_id` pattern not discovered"
        fk = result[0]
        assert fk.is_implicit is True, "canary failed: implicit field not marked is_implicit"
        assert fk.target_model is Dashboard
        assert fk.scope == "team"

    def test_many_related_unscoped_is_flagged(self) -> None:
        """Canary for ManyRelatedField — unscoped many=True PK field must surface as is_many=True, is_already_scoped=False."""
        from products.dashboards.backend.models.dashboard import Dashboard

        class _VulnerableManySerializer(serializers.ModelSerializer):
            related_dashboards = serializers.PrimaryKeyRelatedField(
                many=True, queryset=Dashboard.objects.all(), required=False
            )

            class Meta:
                model = Insight
                fields = ["id", "related_dashboards"]

        result = discover_writable_tenant_fks(_VulnerableManySerializer)
        assert len(result) == 1, "canary failed: M2M many=True field not discovered"
        fk = result[0]
        assert fk.is_many is True, "canary failed: M2M field not marked is_many"
        assert fk.is_already_scoped is False, (
            "canary failed: discovery marked an UNSCOPED many=True PK field as already_scoped"
        )
        assert fk.target_model is Dashboard

    def test_many_related_scoped_is_marked_already_scoped(self) -> None:
        from products.dashboards.backend.models.dashboard import Dashboard

        class _SafeManySerializer(serializers.ModelSerializer):
            related_dashboards = TeamScopedPrimaryKeyRelatedField(
                many=True, queryset=Dashboard.objects.all(), required=False
            )

            class Meta:
                model = Insight
                fields = ["id", "related_dashboards"]

        result = discover_writable_tenant_fks(_SafeManySerializer)
        assert len(result) == 1
        fk = result[0]
        assert fk.is_many is True
        assert fk.is_already_scoped is True, (
            "canary failed: discovery did not recognize TeamScopedPrimaryKeyRelatedField(many=True) as scoped"
        )

    def test_post_body_factory_omits_optional_fields(self) -> None:
        """Canary for the POST body synthesizer.

        If `build_minimal_post_body` ever starts including optional fields,
        the FK-in-POST test will trip noise from validators on those fields
        instead of cleanly failing on the FK we care about.
        """
        from posthog.test.idor.body_factory import build_minimal_post_body

        class _Team:
            pk = 0
            id = 0

        class _OptionalCharSerializer(serializers.Serializer):
            name = serializers.CharField(required=False)

        body = build_minimal_post_body(_OptionalCharSerializer, team=_Team)  # type: ignore[arg-type]
        assert body == {}, f"canary failed: optional field synthesized into POST body: {body!r}"

    def test_post_body_factory_raises_on_unfillable(self) -> None:
        """If body synthesis silently returns garbage instead of raising, the FK POST test
        would receive a 4xx for the wrong reason and look like it 'passed'."""
        from posthog.test.idor.body_factory import BodyUnfillable, build_minimal_post_body

        class _Team:
            pk = 0
            id = 0

        class _Unsupported(serializers.Serializer):
            blob = serializers.FileField(required=True)

        try:
            build_minimal_post_body(_Unsupported, team=_Team)  # type: ignore[arg-type]
        except BodyUnfillable:
            return
        raise AssertionError("canary failed: build_minimal_post_body did not raise on unsupported field")


if __name__ == "__main__":
    unittest.main()
