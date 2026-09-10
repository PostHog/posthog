from typing import Optional

from products.approvals.backend.actions.base import BaseAction

ACTION_REGISTRY: dict[str, type[BaseAction]] = {}


def register_actions():
    from products.approvals.backend.actions.feature_flags import (
        DisableFeatureFlagAction,
        EnableFeatureFlagAction,
        UpdateFeatureFlagAction,
    )

    ACTION_REGISTRY[EnableFeatureFlagAction.key] = EnableFeatureFlagAction
    ACTION_REGISTRY[DisableFeatureFlagAction.key] = DisableFeatureFlagAction
    ACTION_REGISTRY[UpdateFeatureFlagAction.key] = UpdateFeatureFlagAction


def get_action(action_key: str) -> Optional[type[BaseAction]]:
    if not ACTION_REGISTRY:
        register_actions()
    return ACTION_REGISTRY.get(action_key)
