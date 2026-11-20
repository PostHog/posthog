import json

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.entitlements.contracts import Entitlements, FeatureEntry
from posthog.models.organization import ProductFeature


class TestEntitlements(SimpleTestCase):
    def test_canonical_snapshot_ignores_order_and_presentation(self) -> None:
        features: list[ProductFeature] = [
            {
                "key": "retention",
                "limit": 12,
                "unit": "month",
                "name": "Retention",
                "note": "Shown in billing",
                "description": "Retention period",
                "is_plan_default": True,
            },
            {
                "key": "exports",
                "limit": None,
                "unit": None,
                "name": "Exports",
                "note": None,
                "description": "Exports",
                "is_plan_default": False,
            },
        ]
        current = Entitlements.from_features(features)
        reordered_features: list[ProductFeature] = [{**features[1], "description": "Changed copy"}, features[0]]
        reordered = Entitlements.from_features(reordered_features)

        assert current == reordered
        assert current.to_snapshot() == [
            {"key": "exports", "limit": None, "unit": None},
            {"key": "retention", "limit": 12, "unit": "month"},
        ]
        assert Entitlements.from_features(json.loads(json.dumps(current.to_snapshot()))) == current

    @parameterized.expand(
        [
            ("unbounded", {"key": "exports"}, None, None),
            ("zero", {"key": "exports", "limit": 0, "unit": "export"}, 0, "export"),
            ("integer", {"key": "exports", "limit": 30, "unit": "arbitrary-unit"}, 30, "arbitrary-unit"),
        ]
    )
    def test_preserves_limits_units_and_presence(
        self, _name: str, feature: FeatureEntry, limit: int | None, unit: str | None
    ) -> None:
        current = Entitlements.from_features([feature])

        assert current.has("exports")
        assert not current.has("absent")
        assert current.limit("exports") == limit
        assert current.limit("absent") is None
        assert current.to_snapshot() == [{"key": "exports", "limit": limit, "unit": unit}]
        assert current.keys() == frozenset({"exports"})

    @parameterized.expand(
        [
            ("one", frozenset({"retention"}), [{"key": "retention", "limit": 12, "unit": "month"}]),
            ("absent", frozenset({"absent"}), []),
            ("empty", frozenset(), []),
        ]
    )
    def test_restriction_excludes_unowned_features(
        self, _name: str, keys: frozenset[str], expected: list[FeatureEntry]
    ) -> None:
        current = Entitlements.from_features([{"key": "retention", "limit": 12, "unit": "month"}, {"key": "exports"}])

        assert current.restricted_to(keys).to_snapshot() == expected

    def test_inputs_and_exported_snapshots_cannot_mutate_entitlements(self) -> None:
        feature: FeatureEntry = {"key": "retention", "limit": 12}
        current = Entitlements.from_features([feature])
        feature["limit"] = 24
        snapshot = current.to_snapshot()
        snapshot[0]["limit"] = 36

        assert current.limit("retention") == 12

    def test_duplicate_features_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate entitlement feature key"):
            Entitlements.from_features([{"key": "exports"}, {"key": "exports", "limit": 1}])
