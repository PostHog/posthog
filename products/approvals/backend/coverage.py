"""Which approval families cover a flag, and whether a change of owner would drop that cover.

Scoping policies by flag owner means a flag's cover follows its owner. Pointing a product at a
flag therefore changes which policies govern it, and for a product with no family of its own it
removes every one of them. That makes adoption a way around a policy rather than a routine edit,
so the paths that adopt a flag ask here first.
"""

from typing import Any, Optional, cast

from posthog.dataclasses import frozen

from products.approvals.backend import decorators
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

    Read off the actions the flag write gate offers rather than the registry, so a policy counts as
    cover only when the gate evaluates it.
    """
    # Deferred: the flag API module reaches this module through the adoption guard, so an eager
    # import would be circular.
    from products.feature_flags.backend.api.feature_flag import FLAG_WRITE_APPROVAL_ACTIONS  # noqa: PLC0415

    actions: list[FlagWriteAction] = []
    for action in decorators._resolve_actions(list(FLAG_WRITE_APPROVAL_ACTIONS)):
        if not hasattr(action, "owner_scope") or not hasattr(action, "gated_operation"):
            continue
        actions.append(
            FlagWriteAction(
                owner_scope=cast(Optional[str], action.owner_scope),
                operation=cast(str, action.gated_operation),
                key=cast(str, action.key),
            )
        )
    return actions


@frozen
class WriteGate:
    """What an enabled policy asks of one flag write."""

    # The changes it gates. Empty gates every change.
    conditions: dict[str, Any]
    # Who skips it: organization membership levels, and role ids.
    bypass_levels: frozenset[int]
    bypass_role_ids: frozenset[str]

    def stops_everything_stopped_by(self, other: "WriteGate") -> bool:
        """Whether this gate stops every write that `other` stops, for every member."""
        if self.conditions and self.conditions != other.conditions:
            return False
        return self.bypass_levels <= other.bypass_levels and self.bypass_role_ids <= other.bypass_role_ids


def governing_gates(owner_kind: Optional[str], team, organization) -> dict[str, WriteGate]:
    """For each write an enabled policy governs on this product's flags, what that policy asks."""
    engine = PolicyEngine()
    governed: dict[str, WriteGate] = {}
    for action in _flag_write_actions():
        if action.owner_scope != owner_kind:
            continue
        policy = engine.get_policy(action.key, team, organization)
        if policy is not None:
            governed[action.operation] = WriteGate(
                conditions=policy.conditions or {},
                bypass_levels=frozenset(int(level) for level in policy.bypass_org_membership_levels or []),
                bypass_role_ids=frozenset(str(role_id) for role_id in policy.bypass_roles.values_list("id", flat=True)),
            )
    return governed


def write_needs_approval(owner_kind: Optional[str], operation: str, team, organization) -> bool:
    """Whether an enabled policy governs this write on a flag that `owner_kind` owns.

    For a caller that must refuse a write up front, because it runs where a change request
    cannot survive.
    """
    family = owner_kind if scope_by_owner_enabled(organization) else None
    return operation in governing_gates(family, team, organization)


def cover_dropped(governed_now: dict[str, WriteGate], governed_after: dict[str, WriteGate]) -> bool:
    """Whether some write governed now is not stopped as fully afterwards."""
    return any(
        operation not in governed_after or not governed_after[operation].stops_everything_stopped_by(gate)
        for operation, gate in governed_now.items()
    )


def _adoption_guard_applies(organization) -> bool:
    """Whether adoption can move a flag out of review in this organization.

    Before scoping, `feature_flag.*` covers every flag whoever owns it. Without the Approvals
    feature, the gate admits every write, so a policy row left behind protects nothing.
    """
    return scope_by_owner_enabled(organization) and decorators._is_approvals_enabled(organization)


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

    The target must also let no more members skip the gate. Otherwise a member that the current
    policy stops could adopt the flag and then make the write unreviewed.

    False before the organization is scoped by flag owner: `feature_flag.*` still covers every
    flag whoever owns it, so no owner change can drop the cover.
    """
    if not _adoption_guard_applies(organization):
        return False
    return cover_dropped(
        governing_gates(current_owner_kind, team, organization),
        governing_gates(target_owner_kind, team, organization),
    )


def adoption_skips_enable_review(
    flag_active: bool,
    current_owner_kind: Optional[str],
    target_owner_kind: str,
    team,
    organization,
) -> bool:
    """Whether adopting an enabled flag would skip the review the target gives to enabling it.

    The target family reviews the move from off to on, for an experiment its launch. A flag
    that is already on never makes that move again, so the adopting product starts live with
    nobody from the target family having reviewed it.

    A flag the target product already owns has been through that family's review, so it is
    not refused.
    """
    if not flag_active or current_owner_kind == target_owner_kind:
        return False
    if not _adoption_guard_applies(organization):
        return False
    return "enable" in governing_gates(target_owner_kind, team, organization)
