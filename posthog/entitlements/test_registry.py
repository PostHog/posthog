from types import SimpleNamespace

from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.entitlements.contracts import EntitlementChange, EntitlementReactor
from posthog.entitlements.registry import EntitlementReactorRegistry, get_entitlement_reactor_registry


def record_change(change: EntitlementChange) -> None:
    pass


def reactor(key: str) -> EntitlementReactor:
    return EntitlementReactor(key=key, feature_keys=frozenset({"exports"}), react=record_change)


class TestEntitlementRegistry(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        get_entitlement_reactor_registry.cache_clear()

    def tearDown(self) -> None:
        get_entitlement_reactor_registry.cache_clear()
        super().tearDown()

    def test_loads_product_declarations_and_selects_only_requested_reactors(self) -> None:
        module = SimpleNamespace(ENTITLEMENT_REACTORS=(reactor("exports"), reactor("retention")))
        with patch(
            "posthog.entitlements.registry.load_product_modules",
            side_effect=lambda name: [module] if name == "entitlement_reactors" else [],
        ):
            registry = get_entitlement_reactor_registry()

        assert registry.selected(["retention"]) == (reactor("retention"),)
        assert registry.selected([]) == ()

    def test_duplicate_keys_across_product_and_core_are_rejected(self) -> None:
        module = SimpleNamespace(ENTITLEMENT_REACTORS=(reactor("exports"),))
        with (
            patch("posthog.entitlements.registry.CORE_ENTITLEMENT_REACTORS", (reactor("exports"),)),
            patch(
                "posthog.entitlements.registry.load_product_modules",
                side_effect=lambda name: [module] if name == "entitlement_reactors" else [],
            ),
            self.assertRaisesRegex(ValueError, "Duplicate entitlement reactor key: exports"),
        ):
            get_entitlement_reactor_registry()

    def test_unknown_keys_are_rejected(self) -> None:
        registry = EntitlementReactorRegistry(reactors=(reactor("exports"),))
        with self.assertRaisesRegex(ValueError, "Unknown entitlement reactor keys: missing"):
            registry.selected(["exports", "missing"])
