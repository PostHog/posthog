from typing import Optional

from products.approvals.backend.actions.base import BaseAction

ACTION_REGISTRY: dict[str, type[BaseAction]] = {}

# Set once the actions defined here are registered. The registry is not empty before that when
# another product registered its own actions first, so emptiness does not tell.
_builtin_actions_registered = False


def register_actions():
    global _builtin_actions_registered
    from products.approvals.backend.actions.experiment_holdouts import (
        DeleteExperimentHoldoutAction,
        UpdateExperimentHoldoutAction,
    )
    from products.approvals.backend.actions.experiments import (
        LaunchExperimentAction,
        PauseExperimentAction,
        UpdateExperimentAction,
    )
    from products.approvals.backend.actions.feature_flags import (
        DisableFeatureFlagAction,
        EnableFeatureFlagAction,
        UpdateFeatureFlagAction,
    )

    ACTION_REGISTRY[EnableFeatureFlagAction.key] = EnableFeatureFlagAction
    ACTION_REGISTRY[DisableFeatureFlagAction.key] = DisableFeatureFlagAction
    ACTION_REGISTRY[UpdateFeatureFlagAction.key] = UpdateFeatureFlagAction
    ACTION_REGISTRY[LaunchExperimentAction.key] = LaunchExperimentAction
    ACTION_REGISTRY[PauseExperimentAction.key] = PauseExperimentAction
    ACTION_REGISTRY[UpdateExperimentAction.key] = UpdateExperimentAction
    ACTION_REGISTRY[UpdateExperimentHoldoutAction.key] = UpdateExperimentHoldoutAction
    ACTION_REGISTRY[DeleteExperimentHoldoutAction.key] = DeleteExperimentHoldoutAction
    _builtin_actions_registered = True


def register_action(action_class: type[BaseAction]) -> None:
    """Register an action that another product defines for an operation it owns.

    Applying an approved change runs the owning product's code, and approvals may not import
    that product. So the product registers its actions here from its AppConfig.ready.
    """
    if not action_class.key:
        raise ValueError(f"{action_class.__name__} has no key")
    ACTION_REGISTRY[action_class.key] = action_class


def get_action(action_key: str) -> Optional[type[BaseAction]]:
    if not _builtin_actions_registered:
        register_actions()
    return ACTION_REGISTRY.get(action_key)
