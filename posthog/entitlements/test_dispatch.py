from uuid import uuid4

import pytest
from unittest.mock import patch

from posthog.entitlements.contracts import Entitlements
from posthog.entitlements.dispatch import dispatch_entitlement_reactions
from posthog.entitlements.registry import EntitlementReactorRegistry


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
