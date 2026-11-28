from typing import Any
from uuid import uuid4

import pytest
from unittest.mock import patch

from posthog.entitlements.contracts import EntitlementReactor
from posthog.entitlements.flags import enabled_reactor_keys
from posthog.entitlements.registry import EntitlementReactorRegistry

REGISTRY = EntitlementReactorRegistry(
    reactors=(
        EntitlementReactor(
            key="fixture", feature_flag="fixture-flag", feature_keys=frozenset({"fixture"}), react=lambda change: None
        ),
        EntitlementReactor(
            key="other", feature_flag="other-flag", feature_keys=frozenset({"other"}), react=lambda change: None
        ),
    )
)


@pytest.mark.parametrize("variant", [False, None, "control", True])
def test_each_reactor_follows_its_own_boolean_local_flag(variant: str | bool | None) -> None:
    organization_id = str(uuid4())

    def evaluate(flag: str, *args: Any, **kwargs: Any) -> str | bool | None:
        return variant if flag == "fixture-flag" else False

    with patch("posthog.ph_client.posthoganalytics.feature_enabled", side_effect=evaluate) as sdk:
        enabled = enabled_reactor_keys(organization_id, registry=REGISTRY)
    assert enabled == (frozenset({"fixture"}) if variant is True else frozenset())
    assert all(call.kwargs["only_evaluate_locally"] is True for call in sdk.call_args_list)
    assert all(call.kwargs["groups"] == {"organization": organization_id} for call in sdk.call_args_list)


def test_empty_registry_evaluates_no_flag() -> None:
    with (
        patch(
            "posthog.entitlements.flags.get_entitlement_reactor_registry",
            return_value=EntitlementReactorRegistry(reactors=()),
        ),
        patch(
            "posthog.ph_client.posthoganalytics.feature_enabled",
            side_effect=AssertionError("Empty registry flag evaluation"),
        ),
    ):
        assert enabled_reactor_keys(str(uuid4())) == frozenset()


@pytest.mark.parametrize("fail_on_error", [True, False])
def test_one_failed_flag_raises_or_turns_every_reactor_off(fail_on_error: bool) -> None:
    def evaluate(flag: str, *args: Any, **kwargs: Any) -> bool:
        if flag == "other-flag":
            raise RuntimeError("flag")
        return True

    with patch("posthog.ph_client.posthoganalytics.feature_enabled", side_effect=evaluate):
        if fail_on_error:
            with pytest.raises(RuntimeError, match="flag"):
                enabled_reactor_keys(str(uuid4()), registry=REGISTRY)
        else:
            assert enabled_reactor_keys(str(uuid4()), registry=REGISTRY, fail_on_error=False) == frozenset()
