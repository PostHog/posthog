"""Which approval families cover a flag, and whether a change of owner would drop that cover.

Scoping policies by flag owner means a flag's cover follows its owner. Pointing a product at a
flag therefore changes which policies govern it, and for a product with no family of its own it
removes every one of them. That makes adoption a way around a policy rather than a routine edit,
so the paths that adopt a flag ask here first.
"""

from typing import Optional, cast

from products.approvals.backend.actions.registry import ACTION_REGISTRY, register_actions
from products.approvals.backend.ownership import scope_by_owner_enabled
from products.approvals.backend.policies import PolicyEngine


def _flag_write_actions() -> list[tuple[Optional[str], str, str]]:
    """Every action that gates a flag write, as (owner kind it governs, operation, action key).

    Read off the registered actions rather than restated, so this cannot describe a scoping the
    gate does not apply.
    """
    register_actions()
    rows: list[tuple[Optional[str], str, str]] = []
    for key, action in ACTION_REGISTRY.items():
        if not hasattr(action, "owner_scope") or not hasattr(action, "gated_operation"):
            # An action that gates something other than a flag write, such as a holdout change.
            continue
        rows.append((cast(Optional[str], action.owner_scope), cast(str, action.gated_operation), key))
    return rows


def families_by_owner_kind() -> dict[Optional[str], set[str]]:
    """Which action keys govern each owner kind once an organization is scoped by flag owner.

    An owner kind missing from the result has no family at all.
    """
    families: dict[Optional[str], set[str]] = {}
    for owner_scope, _operation, key in _flag_write_actions():
        families.setdefault(owner_scope, set()).add(key)
    return families


def _covered_operations(owner_kind: Optional[str], team, organization) -> set[str]:
    """Which writes an enabled policy governs for a flag this product owns."""
    engine = PolicyEngine()
    return {
        operation
        for owner_scope, operation, key in _flag_write_actions()
        if owner_scope == owner_kind and engine.get_policy(key, team, organization) is not None
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
