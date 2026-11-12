from datetime import UTC, datetime

from django.contrib.admin.models import CHANGE, LogEntry
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q

import structlog
from rest_framework import serializers
from social_django.models import UserSocialAuth

from posthog.api.email_verification import email_verification_code_verifier
from posthog.dataclasses import frozen
from posthog.helpers.email_utils import (
    EmailLookupHandler,
    EmailNormalizer,
    EmailValidationHelper,
    reject_lookalike_email_characters,
    reject_plus_addressed_email,
)
from posthog.models.organization import Organization
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.user import User
from posthog.session.activity import revoke_other_sessions
from posthog.tasks.email import send_email_change_emails

logger = structlog.get_logger(__name__)

AMBIGUOUS_MEMBER = "More than one member has this email in a different case. Type it exactly as the account stores it"


def _domain(email: str) -> str:
    # The delivery domain is the segment after the last "@". Splitting on the first "@" would let an
    # address with two of them pass a verified domain check with a domain that mail never reaches.
    return email.rsplit("@", 1)[-1].lower()


@frozen
class RequestedEmailChange:
    current_email: str
    # None takes the part before the @ of the current email and puts it on the new domain.
    new_email: str | None = None


@frozen
class MemberEmailChange:
    """What happens to one requested change. `skip_reason` is None when the email changes."""

    current_email: str
    new_email: str | None
    user: User | None
    skip_reason: str | None

    @property
    def changes(self) -> bool:
        return self.skip_reason is None


class MemberEmailMigration:
    """Changes the emails of an organization's members without the member verifying the new address.

    The member proves nothing here, so the organization must have verified both the current and the new
    domain. That limits the change to addresses the organization controls, the same rule SCIM applies.
    """

    def __init__(
        self, organization: Organization, requested: list[RequestedEmailChange], new_domain: str | None
    ) -> None:
        self.organization = organization
        self.requested = requested
        self.new_domain = new_domain

    @staticmethod
    def verified_domains(organization: Organization) -> set[str]:
        domains = OrganizationDomain.objects.verified_domains().filter(organization=organization)
        return {domain.lower() for domain in domains.values_list("domain", flat=True)}

    @staticmethod
    def eligible_emails(organization: Organization, limit: int) -> list[str]:
        """Emails of members on a verified domain of the organization, in email order."""
        on_verified_domain = Q()
        for domain in MemberEmailMigration.verified_domains(organization):
            on_verified_domain |= Q(email__iendswith=f"@{domain}")
        if not on_verified_domain:
            return []
        members = organization.members.filter(on_verified_domain, is_staff=False).order_by("email")
        return list(members.values_list("email", flat=True)[:limit])

    def plan(self) -> list[MemberEmailChange]:
        verified = self.verified_domains(self.organization)
        # Legacy accounts can differ only by case, so one folded address can hold more than one member.
        members: dict[str, list[User]] = {}
        for member in self.organization.members.all():
            members.setdefault(member.email.lower(), []).append(member)
        seen_users: set[int] = set()
        seen_targets: set[str] = set()
        changes = []
        for request in self.requested:
            matches = members.get(request.current_email.lower(), [])
            exact = [member for member in matches if member.email == request.current_email]
            candidates = exact or matches
            user = candidates[0] if len(candidates) == 1 else None
            new_email = self._new_email(request, user)
            if len(candidates) > 1:
                skip_reason: str | None = AMBIGUOUS_MEMBER
            else:
                skip_reason = self._skip_reason(user, new_email, verified, seen_users, seen_targets)
            if user is not None:
                seen_users.add(user.pk)
            if skip_reason is None and new_email is not None:
                seen_targets.add(new_email.lower())
            changes.append(
                MemberEmailChange(
                    current_email=user.email if user is not None else request.current_email,
                    new_email=new_email,
                    user=user,
                    skip_reason=skip_reason,
                )
            )
        return changes

    def apply(self, *, notify: bool, changed_by: User, reason: str) -> list[MemberEmailChange]:
        """Runs the plan against the current state, so a member who changed since the preview is skipped."""
        results = []
        for change in self.plan():
            if not change.changes or change.user is None or change.new_email is None:
                results.append(change)
                continue
            skip_reason = self._change_email(change.user.pk, change.current_email, change.new_email, changed_by, reason)
            if skip_reason is not None:
                results.append(
                    MemberEmailChange(
                        current_email=change.current_email,
                        new_email=change.new_email,
                        user=change.user,
                        skip_reason=skip_reason,
                    )
                )
                continue
            revoke_other_sessions(change.user, keep_session_key=None)
            if change.user.pending_email:
                email_verification_code_verifier.invalidate(change.user)
            if notify:
                try:
                    send_email_change_emails.delay(
                        datetime.now(UTC).isoformat(), change.user.first_name, change.current_email, change.new_email
                    )
                except Exception:
                    # The email already changed. A failed notice must not stop the rest of the list.
                    logger.exception("member_email_change_notification_failed", user_id=change.user.pk)
            results.append(change)
        return results

    def _change_email(
        self, user_id: int, current_email: str, new_email: str, changed_by: User, reason: str
    ) -> str | None:
        """Changes one member's email. Returns the reason when it does not change."""
        try:
            with transaction.atomic():
                # The plan read this member before earlier rows ran. Read it again under a lock, so a
                # change the member made in between is not overwritten.
                user = User.objects.select_for_update().get(pk=user_id)
                if user.email != current_email or user.is_staff:
                    return "The account changed while this ran"
                user.email = EmailNormalizer.normalize(new_email)
                user.pending_email = None
                user.save(update_fields=["email", "pending_email"])
                # Delete social auth so the identity at the old provider can't keep logging in.
                UserSocialAuth.objects.filter(user=user).delete()
                # The same entry ModelAdmin.log_change writes, so the history on the user's Django admin
                # page shows the change. It commits with the change, so no change is left without history.
                LogEntry.objects.log_actions(
                    user_id=changed_by.pk,
                    queryset=[user],
                    action_flag=CHANGE,
                    change_message=(
                        f"Changed email from {current_email} to {user.email} "
                        f"for organization '{self.organization.name}'. Reason: {reason}"
                    ),
                    single_object=True,
                )
        except IntegrityError:
            return "Another account already uses this email"
        return None

    def _new_email(self, request: RequestedEmailChange, user: User | None) -> str | None:
        if request.new_email:
            return EmailNormalizer.normalize(request.new_email)
        if user is None or not self.new_domain:
            return None
        local_part = user.email.rsplit("@", 1)[0]
        return EmailNormalizer.normalize(f"{local_part}@{self.new_domain}")

    def _skip_reason(
        self, user: User | None, new_email: str | None, verified: set[str], seen_users: set[int], seen_targets: set[str]
    ) -> str | None:
        if user is None:
            return "Not a member of this organization"
        if user.pk in seen_users:
            return "Listed more than once"
        if user.is_staff:
            return "PostHog staff account"
        if new_email is None:
            return "No new email given"
        if _domain(user.email) not in verified:
            return f"The organization has not verified the current domain {_domain(user.email)}"
        try:
            validate_email(new_email)
            reject_plus_addressed_email(new_email)
            reject_lookalike_email_characters(new_email)
        except (ValidationError, serializers.ValidationError):
            return "The new email is not a valid address"
        if len(new_email) > (User._meta.get_field("email").max_length or 0):
            return "The new email is too long"
        if _domain(new_email) not in verified:
            return f"The organization has not verified the new domain {_domain(new_email)}"
        if new_email == user.email:
            return "Already uses this email"
        if new_email.lower() in seen_targets or self._is_taken(new_email, user):
            return "Another account already uses this email"
        return None

    @staticmethod
    def _is_taken(new_email: str, user: User) -> bool:
        return (
            EmailLookupHandler.users_matching_email(new_email).exclude(pk=user.pk).exists()
            or EmailValidationHelper.user_exists_with_stripped_alias(new_email, exclude_user_id=user.pk)
            or EmailValidationHelper.user_exists_with_gmail_canonical(new_email, exclude_user_id=user.pk)
        )
