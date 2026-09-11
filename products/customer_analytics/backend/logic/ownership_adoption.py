"""
Reviewed adoption of commercial roles from a private manifest. Each proposal names the account,
the role, the state a reviewer settled on and a fingerprint of the role's state when they
reviewed it. A proposal is applied only under the Account lock and only while the fingerprint
still matches, so any decision taken in customer analytics after the review wins over the
manifest.
"""

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from django.db import transaction
from django.db.models import Max

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership

from products.customer_analytics.backend.facade.enums import AccountRelationshipSource
from products.customer_analytics.backend.logic import ownership, relationships
from products.customer_analytics.backend.models import Account, AccountRelationship, AccountRelationshipDefinition

ProposedState = Literal["assigned", "empty"]
Disposition = Literal["would_apply", "applied", "already_applied", "fingerprint_changed", "conflict", "invalid"]


@frozen
class RoleProposal:
    account_id: UUID
    role: ownership.OwnershipRole
    state: ProposedState
    expected_fingerprint: str
    user_id: int | None = None

    def __post_init__(self) -> None:
        if self.role not in ownership.OWNERSHIP_ROLES:
            raise ValueError(f"unknown role {self.role!r}; expected one of {ownership.OWNERSHIP_ROLES}")
        if self.state not in ("assigned", "empty"):
            raise ValueError(f"unknown state {self.state!r}; expected 'assigned' or 'empty'")
        if (self.state == "assigned") != (self.user_id is not None):
            raise ValueError("an assigned proposal names a user_id and an empty one does not")


@frozen
class ProposalOutcome:
    proposal: RoleProposal
    disposition: Disposition
    detail: str | None = None


@frozen
class RoleFingerprint:
    account_id: UUID
    external_id: str | None
    role: ownership.OwnershipRole
    fingerprint: str
    managed: bool
    holder_user_id: int | None


def parse_manifest(raw: dict) -> list[RoleProposal]:
    return [
        RoleProposal(
            account_id=UUID(entry["account_id"]),
            role=entry["role"],
            state=entry["state"],
            expected_fingerprint=entry["expected_fingerprint"],
            user_id=entry.get("user_id"),
        )
        for entry in raw["proposals"]
    ]


def export_fingerprints(team_id: int) -> list[RoleFingerprint]:
    """The current fingerprint of every commercial role on every account, for a manifest builder
    to embed as the precondition of its proposals."""
    bindings = ownership.role_bindings(team_id)
    rows: list[RoleFingerprint] = []
    for account in Account.objects.for_team(team_id).order_by("id").iterator():
        for role in ownership.OWNERSHIP_ROLES:
            holder = _active_holder(team_id, account, bindings.definition_id_of(role))
            rows.append(
                RoleFingerprint(
                    account_id=account.id,
                    external_id=account.external_id,
                    role=role,
                    fingerprint=fingerprint(team_id, account, role, bindings),
                    managed=ownership.is_managed(account, role),
                    holder_user_id=holder.user_id if holder is not None else None,
                )
            )
    return rows


def review(team_id: int, proposals: Sequence[RoleProposal], *, apply: bool) -> list[ProposalOutcome]:
    """Check every proposal against the live role state and, with ``apply``, adopt the ones that
    still hold. Each proposal is its own transaction, so one conflict never rolls back the others."""
    return [_review_one(team_id, proposal, apply=apply) for proposal in proposals]


def fingerprint(team_id: int, account: Account, role: ownership.OwnershipRole, bindings: ownership.RoleBindings) -> str:
    """SHA-256 of everything a reviewer's decision rested on: identity, binding, fence, the active
    holder rows, the last transition and the latest audit entry for the account."""
    definition_id = bindings.definition_id_of(role)
    active = (
        list(
            AccountRelationship.objects.for_team(team_id)
            .filter(account=account, definition_id=definition_id, ended_at__isnull=True)
            .order_by("started_at")
            .values_list("id", "user_id", "started_at")
        )
        if definition_id
        else []
    )
    last_ended_at = (
        AccountRelationship.objects.for_team(team_id)
        .filter(account=account, definition_id=definition_id)
        .aggregate(value=Max("ended_at"))["value"]
        if definition_id
        else None
    )
    latest_activity_id = (
        ActivityLog.objects.filter(
            team_id=team_id,
            scope=relationships.ACTIVITY_SCOPE,
            item_id=str(account.id),
            detail__context__definition_id=str(definition_id),
        )
        .order_by("-created_at", "-id")
        .values_list("id", flat=True)
        .first()
        if definition_id
        else None
    )
    fence = ownership.controlled_at(account, role)
    return ownership.canonical_digest(
        {
            "account_id": str(account.id),
            "external_id": account.external_id,
            "role": role,
            "definition_id": str(definition_id) if definition_id else None,
            "controlled_at": fence.isoformat() if fence else None,
            "active": [[str(row_id), user_id, started_at.isoformat()] for row_id, user_id, started_at in active],
            "last_ended_at": last_ended_at.isoformat() if last_ended_at else None,
            "latest_activity_id": str(latest_activity_id) if latest_activity_id else None,
        }
    )


def _active_holder(team_id: int, account: Account, definition_id: UUID | None) -> AccountRelationship | None:
    if definition_id is None:
        return None
    return (
        AccountRelationship.objects.for_team(team_id)
        .filter(account=account, definition_id=definition_id, ended_at__isnull=True)
        .select_related("definition")
        .order_by("started_at")
        .first()
    )


def _definition(team_id: int, definition_id: UUID) -> AccountRelationshipDefinition:
    return AccountRelationshipDefinition.objects.for_team(team_id).get(id=definition_id)


def _outcome(proposal: RoleProposal, disposition: Disposition, detail: str | None = None) -> ProposalOutcome:
    return ProposalOutcome(proposal=proposal, disposition=disposition, detail=detail)


def _review_one(team_id: int, proposal: RoleProposal, *, apply: bool) -> ProposalOutcome:
    with transaction.atomic():
        account = relationships.lock_account(team_id, proposal.account_id)
        if account is None:
            return _outcome(proposal, "invalid", "account_not_found")
        bindings = ownership.role_bindings(team_id)
        definition_id = bindings.definition_id_of(proposal.role)
        if definition_id is None:
            return _outcome(proposal, "invalid", "role_unbound")
        if not account.external_id:
            return _outcome(proposal, "invalid", "account_not_linked")
        holder = _active_holder(team_id, account, definition_id)
        wanted_user_id = proposal.user_id if proposal.state == "assigned" else None
        # A row whose user was deleted still occupies the role, so it matches neither an empty
        # proposal nor an assigned one; it needs a person's decision.
        state_matches = (
            holder is None if wanted_user_id is None else holder is not None and holder.user_id == wanted_user_id
        )
        if ownership.is_managed(account, proposal.role):
            if state_matches:
                return _outcome(proposal, "already_applied")
            # A managed role already carries a decision; the manifest cannot overrule it.
            return _outcome(proposal, "conflict", "role_managed")
        if fingerprint(team_id, account, proposal.role, bindings) != proposal.expected_fingerprint:
            return _outcome(proposal, "fingerprint_changed")
        if holder is not None and not state_matches:
            return _outcome(
                proposal, "conflict", f"held_by_user_{holder.user_id}" if holder.user_id else "held_by_deleted_user"
            )

        membership = None
        if wanted_user_id is not None and holder is None:
            membership = (
                OrganizationMembership.objects.select_related("user")
                .filter(organization_id=account.team.organization_id, user_id=wanted_user_id, user__is_active=True)
                .first()
            )
            if membership is None:
                return _outcome(proposal, "invalid", "user_not_member")
        if not apply:
            return _outcome(proposal, "would_apply")

        actor = relationships.Actor(source=AccountRelationshipSource.MIGRATION)
        if membership is not None:
            # The role is unmanaged here, so the migration source is allowed to fill it.
            relationships.assign(
                team_id=team_id,
                account=account,
                definition=holder.definition if holder is not None else _definition(team_id, definition_id),
                user=membership.user,
                actor=actor,
                emit_event=False,
                replace_active=False,
            )
        relationships.enroll_role(team_id=team_id, account=account, role=proposal.role, actor=actor)
        return _outcome(proposal, "applied")
