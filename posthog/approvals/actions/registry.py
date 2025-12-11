from typing import Optional

from posthog.approvals.actions.base import BaseAction

ACTION_REGISTRY: dict[str, BaseAction] = {}


def register_actions():
    pass  # TODO: Implement action registration


def get_action(action_key: str) -> Optional[BaseAction]:
    if not ACTION_REGISTRY:
        register_actions()
    return ACTION_REGISTRY.get(action_key)
