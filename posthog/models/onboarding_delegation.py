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
    # Forensic trail for delegation state transitions. The generic User activity-log path
    # doesn't cover onboarding_delegated_to_invite (see posthog/models/activity_logging/
    # activity_log.py); logging here lets ops trace "who delegated what, when" via structlog.
    logger.info(
        "onboarding_delegation_set",
        user_id=locked_user.id,
        invite_id=str(invite.id),
        organization_id=str(organization_id),
    )


def cancel_pending_delegation(*, locked_user: User) -> None:
    """Cancel pending delegation invite for a user in a race-safe, org-scoped way."""
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
    """Mark users who delegated through this invite as accepted."""
    now = datetime.now(UTC)
    User.objects.filter(onboarding_delegated_to_invite_id=invite_id).update(onboarding_delegation_accepted_at=now)


def schedule_delegation_side_effects(
    *,
    invite_id: UUID,
    distinct_id: str | None,
    target_email: str,
    message: str,
    step_at_delegation: str,
) -> None:
    """Queue post-commit effects for a created delegation invite."""

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
                event="onboarding delegated",
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
