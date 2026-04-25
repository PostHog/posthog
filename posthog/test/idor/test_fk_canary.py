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


if __name__ == "__main__":
    unittest.main()
