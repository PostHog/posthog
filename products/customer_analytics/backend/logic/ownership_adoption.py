"""
Reviewed adoption of controlled relationships from a private manifest. Each proposal names the
account, the definition, the state a reviewer settled on and a fingerprint of the relationship's
state when they reviewed it. A proposal is applied only under the Account lock and only while the
fingerprint still matches, so any decision taken in customer analytics after the review wins over
the manifest.
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
    definition_id: UUID
    state: ProposedState
    expected_fingerprint: str
    user_id: int | None = None

    def __post_init__(self) -> None:
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
    definition_id: UUID
    definition_name: str
    fingerprint: str
    managed: bool
    holder_user_id: int | None


def parse_manifest(raw: dict) -> list[RoleProposal]:
    return [
        RoleProposal(
            account_id=UUID(entry["account_id"]),
            definition_id=UUID(entry["definition_id"]),
            state=entry["state"],
            expected_fingerprint=entry["expected_fingerprint"],
            user_id=entry.get("user_id"),
        )
        for entry in raw["proposals"]
    ]


def export_fingerprints(team_id: int) -> list[RoleFingerprint]:
    """The current fingerprint of every controlled relationship on every account, for a manifest
    builder to embed as the precondition of its proposals."""
    definitions = list(ownership.controlled_definitions(team_id))
    rows: list[RoleFingerprint] = []
    for account in Account.objects.for_team(team_id).order_by("id").iterator():
        for definition in definitions:
            holder = relationships.active_relationships(team_id, account, definition).first()
            rows.append(
                RoleFingerprint(
                    account_id=account.id,
                    external_id=account.external_id,
                    definition_id=definition.id,
                    definition_name=definition.name,
                    fingerprint=fingerprint(team_id, account, definition),
                    managed=ownership.control_for(account, definition) is not None,
                    holder_user_id=holder.user_id if holder is not None else None,
                )
            )
    return rows


def review(team_id: int, proposals: Sequence[RoleProposal], *, apply: bool) -> list[ProposalOutcome]:
    """Check every proposal against the live relationship state and, with ``apply``, adopt the ones
    that still hold. Each proposal is its own transaction, so one conflict never rolls back the
    others."""
    return [_review_one(team_id, proposal, apply=apply) for proposal in proposals]


def fingerprint(team_id: int, account: Account, definition: AccountRelationshipDefinition) -> str:
    """SHA-256 of everything a reviewer's decision rested on: identity, fence, the active holder
    rows, the last transition and the latest audit entry for the account under the definition."""
    active = list(
        AccountRelationship.objects.for_team(team_id)
        .filter(account=account, definition=definition, ended_at__isnull=True)
        .order_by("started_at")
        .values_list("id", "user_id", "started_at")
    )
    last_ended_at = (
        AccountRelationship.objects.for_team(team_id)
        .filter(account=account, definition=definition)
        .aggregate(value=Max("ended_at"))["value"]
    )
    latest_activity_id = (
        ActivityLog.objects.filter(
            team_id=team_id,
            scope=relationships.ACTIVITY_SCOPE,
            item_id=str(account.id),
            detail__context__definition_id=str(definition.id),
        )
        .order_by("-created_at", "-id")
        .values_list("id", flat=True)
        .first()
    )
    control = ownership.control_for(account, definition)
    return ownership.canonical_digest(
        {
            "account_id": str(account.id),
            "external_id": account.external_id,
            "definition_id": str(definition.id),
            "controlled_at": control.controlled_at.isoformat() if control is not None else None,
            "active": [[str(row_id), user_id, started_at.isoformat()] for row_id, user_id, started_at in active],
            "last_ended_at": last_ended_at.isoformat() if last_ended_at else None,
            "latest_activity_id": str(latest_activity_id) if latest_activity_id else None,
        }
    )


def _outcome(proposal: RoleProposal, disposition: Disposition, detail: str | None = None) -> ProposalOutcome:
    return ProposalOutcome(proposal=proposal, disposition=disposition, detail=detail)


def _review_one(team_id: int, proposal: RoleProposal, *, apply: bool) -> ProposalOutcome:
    with transaction.atomic():
        # The definition lock comes before the account lock, the order enrollment takes, and it
        # holds `is_controlled` still until the proposal is applied or refused.
        definition = ownership.lock_definition(team_id, proposal.definition_id)
        if definition is None or not definition.is_controlled:
            return _outcome(proposal, "invalid", "definition_not_controlled")
        account = relationships.lock_account(team_id, proposal.account_id)
        if account is None:
            return _outcome(proposal, "invalid", "account_not_found")
        if not account.external_id:
            return _outcome(proposal, "invalid", "account_not_linked")
        holder = relationships.active_relationships(team_id, account, definition).first()
        wanted_user_id = proposal.user_id if proposal.state == "assigned" else None
        # A row whose user was deleted still occupies the relationship, so it matches neither an
        # empty proposal nor an assigned one; it needs a person's decision.
        state_matches = (
            holder is None if wanted_user_id is None else holder is not None and holder.user_id == wanted_user_id
        )
        if ownership.control_for(account, definition) is not None:
            if state_matches:
                return _outcome(proposal, "already_applied")
            # A managed relationship already carries a decision; the manifest cannot overrule it.
            return _outcome(proposal, "conflict", "role_managed")
        if fingerprint(team_id, account, definition) != proposal.expected_fingerprint:
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
            # The relationship is unmanaged here, so the migration source is allowed to fill it.
            relationships.assign(
                team_id=team_id,
                account=account,
                definition=definition,
                user=membership.user,
                actor=actor,
                emit_event=False,
                replace_active=False,
            )
        relationships.enroll(team_id=team_id, account=account, definition=definition, actor=actor)
        return _outcome(proposal, "applied")
