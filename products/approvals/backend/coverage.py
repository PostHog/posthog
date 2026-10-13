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


def families_by_owner_kind() -> dict[Optional[str], set[str]]:
    """Which action keys govern each owner kind once an organization is scoped by flag owner.

    Read off the registered actions rather than restated, so this cannot describe a scoping the
    gate does not apply. An owner kind missing from the result has no family at all.
    """
    register_actions()
    families: dict[Optional[str], set[str]] = {}
    for key, action in ACTION_REGISTRY.items():
        if not hasattr(action, "owner_scope"):
            # An action that gates something other than a flag write, such as a holdout change.
            continue
        families.setdefault(cast(Optional[str], action.owner_scope), set()).add(key)
    return families


def _is_covered(owner_kind: Optional[str], team, organization) -> bool:
    """Whether any enabled policy governs a flag this product owns."""
    engine = PolicyEngine()
    keys = families_by_owner_kind().get(owner_kind, set())
    return any(engine.get_policy(key, team, organization) is not None for key in keys)


def adoption_drops_approval_cover(
    current_owner_kind: Optional[str],
    target_owner_kind: str,
    team,
    organization,
) -> bool:
    """Whether pointing this product at the flag would leave it governed by no policy.

    False before the organization is scoped by flag owner: `feature_flag.*` still covers every
    flag whoever owns it, so no owner change can drop the cover.

    False as well when the target product has a family with a policy, which is how an experiment
    adopting a flag stays allowed: the cover moves rather than disappearing.
    """
    if not scope_by_owner_enabled(organization):
        return False
    if not _is_covered(current_owner_kind, team, organization):
        return False
    return not _is_covered(target_owner_kind, team, organization)
