from uuid import uuid4

import pytest
from unittest.mock import patch

from posthog.entitlements.contracts import EntitlementReactor, Entitlements
from posthog.entitlements.dispatch import dispatch_entitlement_reactions, entitlement_reactions_enabled
from posthog.entitlements.registry import EntitlementReactorRegistry


@pytest.mark.parametrize("variant", [False, None, "control", True])
def test_org_flag_is_boolean_and_local_only(variant: str | bool | None) -> None:
    organization_id = str(uuid4())
    with (
        patch(
            "posthog.entitlements.dispatch.get_entitlement_reactor_registry",
            return_value=EntitlementReactorRegistry(
                reactors=(
                    EntitlementReactor(key="fixture", feature_keys=frozenset({"fixture"}), react=lambda change: None),
                )
            ),
        ),
        patch("posthog.ph_client.posthoganalytics.feature_enabled", return_value=variant) as sdk,
    ):
        assert entitlement_reactions_enabled(organization_id) is (variant is True)
    assert sdk.call_args.kwargs["only_evaluate_locally"] is True
    assert sdk.call_args.kwargs["groups"] == {"organization": organization_id}


@pytest.mark.django_db
def test_empty_registry_never_queries_or_evaluates_flag(django_assert_num_queries) -> None:
    with (
        patch(
            "posthog.entitlements.dispatch.get_entitlement_reactor_registry",
            return_value=EntitlementReactorRegistry(reactors=()),
        ),
        patch(
            "posthog.ph_client.posthoganalytics.feature_enabled",
            side_effect=AssertionError("Empty registry flag evaluation"),
        ),
        django_assert_num_queries(0),
    ):
        dispatch_entitlement_reactions(str(uuid4()), Entitlements.from_features([{"key": "fixture"}]))
