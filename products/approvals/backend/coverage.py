"""Which approval families cover a flag, and whether a change of owner would drop that cover.

Scoping policies by flag owner means a flag's cover follows its owner. Pointing a product at a
flag therefore changes which policies govern it, and for a product with no family of its own it
removes every one of them. That makes adoption a way around a policy rather than a routine edit,
so the paths that adopt a flag ask here first.
"""

from typing import Any, Optional, cast

from posthog.dataclasses import frozen

from products.approvals.backend.actions.registry import ACTION_REGISTRY, register_actions
from products.approvals.backend.ownership import scope_by_owner_enabled
from products.approvals.backend.policies import PolicyEngine


@frozen
class FlagWriteAction:
    """One registered action that gates a flag write."""

    # The product whose flags this action governs, or None for the flags no product owns.
    owner_scope: Optional[str]
    # The write it gates. Two families name the same write with different keys.
    operation: str
    key: str


def _flag_write_actions() -> list[FlagWriteAction]:
    """Every action that gates a flag write.

    Read off the registered actions rather than restated, so this cannot describe a scoping the
    gate does not apply.
    """
    register_actions()
    actions: list[FlagWriteAction] = []
    for key, action in ACTION_REGISTRY.items():
        if not hasattr(action, "owner_scope") or not hasattr(action, "gated_operation"):
            # An action that gates something other than a flag write, such as a holdout change.
            continue
        actions.append(
            FlagWriteAction(
                owner_scope=cast(Optional[str], action.owner_scope),
                operation=cast(str, action.gated_operation),
                key=key,
            )
        )
    return actions


def families_by_owner_kind() -> dict[Optional[str], set[str]]:
    """Which action keys govern each owner kind once an organization is scoped by flag owner.

    An owner kind missing from the result has no family at all.
    """
    families: dict[Optional[str], set[str]] = {}
    for action in _flag_write_actions():
        families.setdefault(action.owner_scope, set()).add(action.key)
    return families


def _governing_conditions(owner_kind: Optional[str], team, organization) -> dict[str, dict[str, Any]]:
    """For each write an enabled policy governs on this product's flags, that policy's conditions."""
    engine = PolicyEngine()
    governed: dict[str, dict[str, Any]] = {}
    for action in _flag_write_actions():
        if action.owner_scope != owner_kind:
            continue
        policy = engine.get_policy(action.key, team, organization)
        if policy is not None:
            governed[action.operation] = policy.conditions or {}
    return governed


def adoption_drops_approval_cover(
    current_owner_kind: Optional[str],
    target_owner_kind: str,
    team,
    organization,
) -> bool:
    """Whether pointing this product at the flag would leave some write of it less governed.

    Compared write by write. For each write governed now, the target family must gate at least
    the same changes, which a policy does in two cases:

    - It has no conditions, so it gates every such write.
    - It has the same conditions, so it gates the same writes. Each experiment action subclasses
      the flag action for the same write and builds the same intent, so equal conditions evaluate
      equally. This is what keeps the synced mirrors, which copy conditions exactly, allowed.

    A target policy that merely exists is not enough. One whose conditions name a field the write
    never carries matches nothing, and the gate reads an unmatched condition as "allow", so it
    would let through the write the current policy stopped.

    False before the organization is scoped by flag owner: `feature_flag.*` still covers every
    flag whoever owns it, so no owner change can drop the cover.
    """
    if not scope_by_owner_enabled(organization):
        return False
    governed_now = _governing_conditions(current_owner_kind, team, organization)
    governed_after = _governing_conditions(target_owner_kind, team, organization)
    for operation, conditions in governed_now.items():
        if operation not in governed_after:
            return True
        target_conditions = governed_after[operation]
        if target_conditions and target_conditions != conditions:
            return True
    return False
