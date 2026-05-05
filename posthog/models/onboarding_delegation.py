from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django.db import transaction

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.user import OnboardingSkippedReason, User

if TYPE_CHECKING:
    from posthog.models.organization_invite import OrganizationInvite


logger = structlog.get_logger(__name__)


def get_existing_pending_delegation_invite(
    *, locked_user: User, organization_id: UUID | str
) -> OrganizationInvite | None:
    """Return an existing pending delegation invite for this user in this org.

    If the stored pointer is stale (wrong org, expired, deleted), clear the delegation
    fields so callers can proceed with a fresh invite.
    """
    # Local import is unavoidable: organization_invite imports this module's helpers, so
    # importing it at module scope would be a circular dependency.
    from posthog.models.organization_invite import OrganizationInvite

    if (
        locked_user.onboarding_delegated_to_invite_id is None
        or locked_user.onboarding_delegation_accepted_at is not None
    ):
        return None

    existing_invite = OrganizationInvite.objects.filter(
        pk=locked_user.onboarding_delegated_to_invite_id,
        organization_id=organization_id,
        is_setup_delegation=True,
        created_by_id=locked_user.id,
    ).first()
    if existing_invite is not None and not existing_invite.is_expired():
        return existing_invite

    clear_delegation_state(locked_user, save=True)
    return None


def set_delegated_state(*, locked_user: User, invite: OrganizationInvite, organization_id: UUID | str) -> None:
    """Mark user as delegated and waiting on a teammate for the given organization.

    If the user already had a pending delegation pointing at a different invite/org, cancel
    that older invite first — the schema only stores one FK, so without this the older invite
    would become orphaned: still live (granting admin on accept) but no longer tracked in
    `onboarding_delegated_to_invite`, and therefore invisible to `pre_delete`'s un-suppress
    receiver and to the "waiting for teammate" UI.

    Also pre-populates the delegator's sidebar with all released products on the team they
    land on after delegating, so the post-delegation home page isn't empty.
    """
    if (
        locked_user.onboarding_delegated_to_invite_id is not None
        and locked_user.onboarding_delegation_accepted_at is None
        and locked_user.onboarding_delegated_to_invite_id != invite.id
    ):
        cancel_pending_delegation(locked_user=locked_user)

    locked_user.onboarding_delegated_to_invite = invite
    locked_user.onboarding_delegated_to_organization_id = organization_id
    locked_user.onboarding_skipped_at = datetime.now(UTC)
    locked_user.onboarding_skipped_reason = OnboardingSkippedReason.DELEGATED
    # Also scope the skip to the same org: stops the onboarding redirect here but not in other
    # orgs the user might belong to.
    locked_user.onboarding_skipped_organization_id = organization_id
    locked_user.onboarding_delegation_accepted_at = None
    locked_user.save(
        update_fields=[
            "onboarding_delegated_to_invite",
            "onboarding_delegated_to_organization_id",
            "onboarding_skipped_at",
            "onboarding_skipped_reason",
            "onboarding_skipped_organization_id",
            "onboarding_delegation_accepted_at",
        ]
    )
    # Sidebar seeding runs ~37 get_or_create calls (one per released product). Defer it
    # to post-commit so the held select_for_update locks on Organization and User aren't
    # extended by dozens of sequential DB roundtrips.
    user_id = locked_user.id

    def _seed_after_commit() -> None:
        _seed_sidebar_for_delegator(user_id=user_id, organization_id=organization_id)

    transaction.on_commit(_seed_after_commit)

    # Forensic trail for delegation state transitions. The generic User activity-log path
    # doesn't cover onboarding_delegated_to_invite (see posthog/models/activity_logging/
    # activity_log.py); logging here lets ops trace "who delegated what, when" via structlog.
    logger.info(
        "onboarding_delegation_set",
        user_id=locked_user.id,
        invite_id=str(invite.id),
        organization_id=str(organization_id),
    )


def _seed_sidebar_for_delegator(*, user_id: int, organization_id: UUID | str) -> None:
    """Enable all released products on the delegator's sidebar for the delegated org.

    The post-delegation home page would otherwise be empty (no product intents recorded
    during a skipped onboarding). We seed against the user's current_team if it's in the
    delegated org; otherwise pick any team in the org they have access to. A failure here
    must not block the delegation itself, so we swallow exceptions after capturing them.
    """
    # Local imports to avoid pulling Team and UserProductList (and their transitive model
    # graph) into module-load order — onboarding_delegation is imported by Django model
    # modules during app loading and module-level cross-model imports here have triggered
    # apps-not-ready issues.
    from posthog.models.file_system.user_product_list import UserProductList
    from posthog.models.team.team import Team

    try:
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            return
        team = None
        current_team = user.current_team
        if current_team is not None and str(current_team.organization_id) == str(organization_id):
            team = current_team
        else:
            team = Team.objects.filter(organization_id=organization_id).order_by("id").first()
        if team is None:
            return
        UserProductList.enable_all_for_user(
            user=user,
            team=team,
            reason=UserProductList.Reason.ONBOARDING_DELEGATED,
        )
    except Exception as exc:  # noqa: BLE001 - sidebar seeding must never block delegation
        capture_exception(exc)
        # Pair the Sentry capture with an indexable structured log so ops can correlate
        # broken-sidebar reports back to a specific delegator/org without hunting Sentry.
        logger.warning(
            "delegation_sidebar_seed_failed",
            user_id=user_id,
            organization_id=str(organization_id),
            error=str(exc),
        )


def cancel_pending_delegation(*, locked_user: User) -> None:
    """Cancel pending delegation invite for a user in a race-safe, org-scoped way."""
    # Local import is unavoidable: organization_invite imports this module's helpers.
    from posthog.models.organization_invite import OrganizationInvite

    pending_invite_id = (
        locked_user.onboarding_delegated_to_invite_id if locked_user.onboarding_delegation_accepted_at is None else None
    )
    if pending_invite_id is None:
        return

    pending_invite_qs = OrganizationInvite.objects.filter(
        pk=pending_invite_id,
        is_setup_delegation=True,
        created_by_id=locked_user.id,
    )
    if locked_user.onboarding_delegated_to_organization_id:
        pending_invite_qs = pending_invite_qs.filter(
            organization_id=locked_user.onboarding_delegated_to_organization_id
        )
    pending_invite = pending_invite_qs.first()
    if pending_invite is not None:
        pending_invite.delete()


def clear_delegation_state(locked_user: User, *, save: bool) -> None:
    """Clear delegation pointers/timestamps from user state."""
    prior_invite_id = locked_user.onboarding_delegated_to_invite_id
    prior_org_id = locked_user.onboarding_delegated_to_organization_id
    locked_user.onboarding_delegated_to_invite = None
    locked_user.onboarding_delegated_to_organization_id = None
    locked_user.onboarding_delegation_accepted_at = None
    if save:
        locked_user.save(
            update_fields=[
                "onboarding_delegated_to_invite",
                "onboarding_delegated_to_organization_id",
                "onboarding_delegation_accepted_at",
            ]
        )
    if prior_invite_id is not None:
        logger.info(
            "onboarding_delegation_cleared",
            user_id=locked_user.id,
            prior_invite_id=str(prior_invite_id),
            prior_organization_id=str(prior_org_id) if prior_org_id else None,
        )


def mark_delegators_accepted(*, invite_id: UUID) -> None:
    """Mark users who delegated through this invite as accepted.

    Bulk update to avoid Django signal races against the same transaction; the bulk path
    bypasses ModelActivityMixin, so we emit an explicit structlog entry per affected user
    so the audit trail isn't lost. Filtering on `onboarding_delegation_accepted_at IS NULL`
    preserves "first accepted at" semantics if for any reason this runs twice for the same
    invite — re-acceptance never overwrites the original timestamp.
    """
    now = datetime.now(UTC)
    affected_user_ids = list(
        User.objects.filter(
            onboarding_delegated_to_invite_id=invite_id, onboarding_delegation_accepted_at__isnull=True
        ).values_list("id", flat=True)
    )
    if not affected_user_ids:
        return
    # Clear the denormalized organization_id alongside the FK acceptance stamp so a
    # delegator's row doesn't dangle `onboarding_delegated_to_organization_id` after
    # acceptance. The FK is SET_NULL'd by `self.delete()` immediately after this call.
    User.objects.filter(id__in=affected_user_ids).update(
        onboarding_delegation_accepted_at=now,
        onboarding_delegated_to_organization_id=None,
    )
    logger.info(
        "onboarding_delegation_accepted",
        invite_id=str(invite_id),
        delegator_user_ids=affected_user_ids,
        accepted_at=now.isoformat(),
    )


def schedule_delegation_side_effects(
    *,
    invite_id: UUID,
    distinct_id: str | None,
    target_email: str,
    message: str,
    step_at_delegation: str,
    is_resubmit: bool = False,
) -> None:
    """Queue post-commit effects for a created delegation invite.

    `is_resubmit=True` is set when the caller is replaying side effects on an existing
    invite (the dispatch path for "email never reached the worker" recovery). In that
    case we re-queue the email but emit a distinct analytics event so the
    `onboarding delegated` count remains a true count of delegations rather than a
    count of dispatch attempts.
    """

    def _queue_delegation_email() -> None:
        from posthog.tasks.email import send_invite

        try:
            send_invite_task = cast(Any, send_invite)
            send_invite_task.apply_async(kwargs={"invite_id": invite_id})
            # Do not mark emailing_attempt_made here. The flag is stamped by `send_invite`
            # after `message.send()` returns, so a worker-side failure (SMTP outage,
            # Customer.io rejection) leaves the flag False and the next re-submit retries
            # the email dispatch rather than silently stranding the delegator.
        except Exception as exc:  # noqa: BLE001 - broker outage must not 500 a committed delegation
            capture_exception(exc)

    def _fire_analytics() -> None:
        if not distinct_id:
            return
        try:
            posthoganalytics.capture(
                distinct_id=distinct_id,
                event=("onboarding delegation email retried" if is_resubmit else "onboarding delegated"),
                properties={
                    "target_email_domain": target_email.split("@")[-1] if "@" in target_email else None,
                    "has_message": bool(message),
                    "step_at_delegation": step_at_delegation or None,
                    "invite_id": str(invite_id),
                },
            )
        except Exception as exc:  # noqa: BLE001
            capture_exception(exc)

    transaction.on_commit(_queue_delegation_email)
    transaction.on_commit(_fire_analytics)
