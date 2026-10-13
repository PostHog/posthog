"""Which approval families cover a flag, and whether a change of owner would drop that cover.

Scoping policies by flag owner means a flag's cover follows its owner. Pointing a product at a
flag therefore changes which policies govern it, and for a product with no family of its own it
removes every one of them. That makes adoption a way around a policy rather than a routine edit,
so the paths that adopt a flag ask here first.
"""

from typing import Optional, cast

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


def _covered_operations(owner_kind: Optional[str], team, organization) -> set[str]:
    """Which writes an enabled policy governs for a flag this product owns."""
    engine = PolicyEngine()
    return {
        action.operation
        for action in _flag_write_actions()
        if action.owner_scope == owner_kind and engine.get_policy(action.key, team, organization) is not None
    }


def adoption_drops_approval_cover(
    current_owner_kind: Optional[str],
    target_owner_kind: str,
    team,
    organization,
) -> bool:
    """Whether pointing this product at the flag would leave some write of it ungoverned.

    Compared operation by operation, not family by family. A family covering *something* is not
    enough: a flag protected against being enabled, adopted into a family that gates only pausing,
    would lose exactly the protection it had. So each write governed now must still be governed
    after, and losing any one of them refuses the adoption.

    False before the organization is scoped by flag owner: `feature_flag.*` still covers every
    flag whoever owns it, so no owner change can drop the cover.
    """
    if not scope_by_owner_enabled(organization):
        return False
    governed_now = _covered_operations(current_owner_kind, team, organization)
    return bool(governed_now - _covered_operations(target_owner_kind, team, organization))
