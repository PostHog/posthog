from datetime import timedelta
from typing import TYPE_CHECKING, Optional, cast

from django.db import models, transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

import structlog
from rest_framework import exceptions

from posthog.constants import INVITE_DAYS_VALIDITY
from posthog.email import is_email_available
from posthog.helpers.email_utils import EmailNormalizer, EmailValidationHelper
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.file_system.user_product_list import backfill_user_product_list_for_new_user
from posthog.models.onboarding_delegation import mark_delegators_accepted
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.utils import UUIDTModel, sane_repr
from posthog.utils import absolute_uri

from ee.models.rbac.access_control import AccessControl

if TYPE_CHECKING:
    from posthog.models import User


logger = structlog.get_logger(__name__)

# In ordinary use one delegation invite maps to one delegator; if we ever see more than this
# being unsuppressed by a single invite delete, the logic invariant has drifted and ops should
# investigate rather than silently bulk-update many User rows.
_DELEGATION_UNSUPPRESS_WARN_THRESHOLD = 5


def validate_private_project_access(value):
    from posthog.rbac.user_access_control import ACCESS_CONTROL_LEVELS_MEMBER

    if not isinstance(value, list):
        raise exceptions.ValidationError("The field must be a list of dictionaries.")
    for item in value:
        if not isinstance(item, dict):
            raise exceptions.ValidationError("Each item in the list must be a dictionary.")
        if "id" not in item or "level" not in item:
            raise exceptions.ValidationError('Each dictionary must contain "id" and "level" keys.')
        if not isinstance(item["id"], int):
            raise exceptions.ValidationError('The "id" field must be an integer.')
        valid_levels = list(ACCESS_CONTROL_LEVELS_MEMBER)
        if item["level"] not in valid_levels:
            raise exceptions.ValidationError('The "level" field must be a valid access level.')


class InviteExpiredException(exceptions.ValidationError):
    def __init__(self, message="This invite has expired. Please ask your admin for a new one."):
        super().__init__(message, code="expired")


class OrganizationInvite(ModelActivityMixin, UUIDTModel):
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="invites",
        related_query_name="invite",
    )
    target_email = models.EmailField(null=True, db_index=True)
    first_name = models.CharField(max_length=30, blank=True, default="")
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        related_name="organization_invites",
        related_query_name="organization_invite",
        null=True,
    )
    emailing_attempt_made = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    message = models.TextField(blank=True, null=True)
    level = models.PositiveSmallIntegerField(
        default=OrganizationMembership.Level.MEMBER, choices=OrganizationMembership.Level
    )
    private_project_access = models.JSONField(
        default=list,
        null=True,
        blank=True,
        help_text="List of team IDs and corresponding access levels to private projects.",
        validators=[validate_private_project_access],
    )
    is_setup_delegation = models.BooleanField(
        default=False,
        help_text=(
            "True when this invite was created via the onboarding delegation flow. "
            "Downstream logic routes the delegate through full onboarding on accept."
        ),
    )

    def validate(
        self,
        *,
        user: Optional["User"] = None,
        email: Optional[str] = None,
        invite_email: Optional[str] = None,
        request_path: Optional[str] = None,
    ) -> None:
        _email = email or getattr(user, "email", None)

        if (
            _email
            and self.target_email
            and EmailNormalizer.normalize(_email) != EmailNormalizer.normalize(self.target_email)
        ):
            raise exceptions.ValidationError(
                "This invite is intended for another email address.",
                code="invalid_recipient",
            )

        if self.is_expired():
            raise InviteExpiredException()

        if user is None and invite_email and EmailValidationHelper.user_exists(invite_email):
            raise exceptions.ValidationError(f"/login?next={request_path}", code="account_exists")

        if OrganizationMembership.objects.filter(organization=self.organization, user=user).exists():
            raise exceptions.ValidationError(
                "You already are a member of this organization.",
                code="user_already_member",
            )

        if (
            self.target_email
            and OrganizationMembership.objects.filter(
                organization=self.organization, user__email__iexact=self.target_email
            ).exists()
        ):
            raise exceptions.ValidationError(
                "Another user with this email address already belongs to this organization.",
                code="existing_email_address",
            )

    def use(self, user: "User", *, prevalidated: bool = False) -> None:
        if not prevalidated:
            self.validate(user=user)
        # Wrap the membership creation, inviter attribution, private-project grants, and invite
        # cleanup in one atomic block so a crash mid-flow can't leave the membership without its
        # inviter, nor delete the invite before the membership is fully wired up.
        #
        # Lock ordering invariant: the accept path locks `OrganizationInvite` (here) and may
        # then bulk-update `User` rows via `mark_delegators_accepted`. The delegation-create
        # path in `posthog/api/organization_invite.py:delegate` locks `Organization` then
        # `User`. The two paths share `User` writes but never both hold `OrganizationInvite`
        # and `Organization` simultaneously, so they cannot deadlock as long as
        # `mark_delegators_accepted` only updates users tied to *this* invite (it filters on
        # `onboarding_delegated_to_invite_id=self.id`). Do not extend either path to cross-lock
        # without re-checking the order.
        with transaction.atomic():
            # Row-lock the invite so two concurrent accepts of the same link serialize on this
            # row rather than racing each other into the membership/grant path. Without this
            # lock the second transaction would see the invite row and proceed before the first
            # had committed its membership / delegator-accepted updates. If the first transaction
            # already deleted the row, surface a friendly InviteExpiredException rather than a 500.
            try:
                OrganizationInvite.objects.select_for_update().get(pk=self.pk)
            except OrganizationInvite.DoesNotExist:
                raise InviteExpiredException("This invite has already been used.")

            membership = user.join(organization=self.organization, level=cast(OrganizationMembership.Level, self.level))
            if self.created_by_id is not None:
                # Bypass ModelActivityMixin on this follow-up write: the membership row was just
                # created one line above, and a "created" signal has already fired. An "updated"
                # signal here would be spurious noise and adds a pre-update query.
                OrganizationMembership.objects.filter(pk=membership.pk).update(invited_by_id=self.created_by_id)
                membership.invited_by_id = self.created_by_id

            if self.is_setup_delegation:
                self._mark_delegators_accepted(user)

            for item in self.private_project_access or []:
                try:
                    team: Team = self.organization.teams.get(id=item["id"])
                    parent_membership = OrganizationMembership.objects.get(
                        organization=self.organization,
                        user=user,
                    )
                except self.organization.teams.model.DoesNotExist:
                    # If the team doesn't exist, it was probably deleted. We can still continue with the invite.
                    continue

                AccessControl.objects.create(
                    team=team,
                    resource="project",
                    resource_id=str(team.id),
                    organization_member=parent_membership,
                    access_level=item["level"],
                )

            # Sibling-invite sweep: clean up any other pending invites for the same email in this
            # org so the invitee doesn't accumulate stale rows. Other DELEGATION invites have
            # already produced a real outcome (the same person just accepted), so their delegators
            # need to be stamped accepted before the pre_delete un-suppress receiver runs on
            # those siblings — otherwise it bounces those delegators back into onboarding.
            sibling_qs = OrganizationInvite.objects.filter(
                organization=self.organization,
                target_email__iexact=self.target_email,
            ).exclude(pk=self.pk)
            sibling_delegation_ids = list(sibling_qs.filter(is_setup_delegation=True).values_list("id", flat=True))
            # Materialize sibling pks first, then delete one-by-one. Stamping `accepted_at`
            # *after* each delete commits avoids leaving orphan "accepted" markers on
            # delegators if a bulk delete raises mid-way (we'd otherwise have stamped state
            # for invites that still live, producing hard-to-audit drift).
            sibling_pks = list(sibling_qs.values_list("pk", flat=True))
            for sibling_pk in sibling_pks:
                OrganizationInvite.objects.filter(pk=sibling_pk).delete()
                if sibling_pk in sibling_delegation_ids:
                    mark_delegators_accepted(invite_id=sibling_pk)
            self.delete()

        # Side effects that don't need the membership/invite rows are fine to run after commit.
        self._sync_user_product_list_for_accessible_teams(user)

        if is_email_available(with_absolute_urls=True):
            from posthog.tasks.email import send_member_join

            send_member_join.apply_async(
                kwargs={
                    "invitee_uuid": user.uuid,
                    "organization_id": self.organization_id,
                }
            )

    def _mark_delegators_accepted(self, accepting_user: "User") -> None:
        # Scope strictly to users who actually delegated through THIS invite. The accepting
        # user is NOT a delegator of this invite — stamping them would corrupt the field's
        # meaning for anyone who happens to be both a delegate here and a delegator elsewhere.
        mark_delegators_accepted(invite_id=self.id)

    def _sync_user_product_list_for_accessible_teams(self, user: "User") -> None:
        """Sync UserProductList for all teams the user has access to."""
        from posthog.rbac.user_access_control import UserAccessControl

        uac = UserAccessControl(user=user, organization_id=str(self.organization.id))
        accessible_teams = uac.filter_queryset_by_access_level(self.organization.teams.all(), include_all_if_admin=True)

        for team in accessible_teams:
            backfill_user_product_list_for_new_user(user, team)

    def is_expired(self) -> bool:
        """Check if invite is older than INVITE_DAYS_VALIDITY days."""
        return self.created_at < timezone.now() - timedelta(INVITE_DAYS_VALIDITY)

    def delete(self, *args, **kwargs):
        from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated
        from posthog.models.signals import model_activity_signal

        model_activity_signal.send(
            sender=self.__class__,
            scope=self.__class__.__name__,
            before_update=self,
            after_update=None,
            activity="deleted",
            user=get_current_user(),
            was_impersonated=get_was_impersonated(),
        )
        return super().delete(*args, **kwargs)

    def __str__(self):
        return absolute_uri(f"/signup/{self.id}")

    __repr__ = sane_repr("organization", "target_email", "created_by")


# pre_delete fires BEFORE Django's Collector runs the SET_NULL update on User FKs pointing
# at this invite, so we can still see which users delegated through it. It fires for both
# instance.delete() and QuerySet.delete() (bulk deletes from use(), admin panel, cascade,
# or cleanup jobs all go through Collector). Matching on the FK alone (not on the
# denormalized reason) avoids a stuck-forever bug if the two fields ever drift.
@receiver(pre_delete, sender=OrganizationInvite)
def _unsuppress_delegator_onboarding_on_invite_delete(sender, instance: OrganizationInvite, **kwargs) -> None:
    """Re-enable onboarding only for delegators whose delegation is still pending.

    Intent table:
    - invite accepted -> do nothing here (accepted users keep onboarding suppressed)
    - invite cancelled/expired/deleted before acceptance -> clear suppression so onboarding resumes
    """
    if not instance.is_setup_delegation:
        return

    from django.db.models import Q

    from posthog.models.user import OnboardingSkippedReason, User

    # Accepting a delegation invite marks delegators with onboarding_delegation_accepted_at.
    # We only "un-suppress" users who still have a pending delegation (accepted_at is null),
    # i.e. explicit cancellation/expiry paths. This avoids bouncing accepted delegators back
    # into onboarding immediately after their teammate accepts.
    #
    # We also catch already-NULLed stale rows: if a parallel `clear_delegation_state` or
    # cascade SET_NULL ran first, the FK is gone but `onboarding_skipped_reason="delegated"`
    # plus `onboarding_delegated_to_organization_id` may still be set, leaving the user
    # permanently suppressed with no recovery path. Match those rows by the denormalized
    # org_id so they're un-suppressed alongside the FK-matched ones.
    #
    # The org-scoped branch is intentionally narrow: it requires no surviving FK to ANY
    # delegation invite so we don't fan out to delegators with a different, still-live
    # delegation. Scoping it that way keeps cleanup propagation tied to the cache key
    # (the invite being deleted) rather than the larger org boundary.
    surviving_delegation_invite_ids = (
        OrganizationInvite.objects.filter(organization_id=instance.organization_id, is_setup_delegation=True)
        .exclude(pk=instance.pk)
        .values_list("pk", flat=True)
    )
    pending_delegators = User.objects.filter(
        Q(onboarding_delegated_to_invite_id=instance.id)
        | Q(
            onboarding_delegated_to_invite_id__isnull=True,
            onboarding_delegated_to_organization_id=instance.organization_id,
            onboarding_skipped_reason=OnboardingSkippedReason.DELEGATED,
        ),
        onboarding_delegation_accepted_at__isnull=True,
    ).exclude(onboarding_delegated_to_invite_id__in=surviving_delegation_invite_ids)
    # Capture affected user IDs BEFORE the update so the audit log can enumerate them. In
    # ordinary use this is a single row (one delegator per invite); capping the logged list
    # to the warn threshold bounds the payload size if the invariant ever drifts.
    affected_user_ids = list(pending_delegators.values_list("id", flat=True))
    affected_count = len(affected_user_ids)
    if affected_count == 0:
        return
    User.objects.filter(id__in=affected_user_ids).update(
        onboarding_skipped_at=None,
        onboarding_skipped_reason=None,
        onboarding_skipped_organization_id=None,
        onboarding_delegated_to_organization_id=None,
        onboarding_delegation_accepted_at=None,
    )
    if affected_count > _DELEGATION_UNSUPPRESS_WARN_THRESHOLD:
        logger.warning(
            "delegation_invite_delete_unsuppressed_many_users",
            invite_id=str(instance.id),
            organization_id=str(instance.organization_id) if instance.organization_id else None,
            affected_count=affected_count,
        )
    # Audit trail: bulk .update() bypasses ModelActivityMixin signals; log explicitly so ops
    # can trace why a delegator's onboarding state was cleared. Cap the user-id list to the
    # warn threshold to bound payload size while still being useful in normal-volume cases.
    logger.info(
        "delegation_invite_deleted_unsuppressed_delegators",
        invite_id=str(instance.id),
        organization_id=str(instance.organization_id) if instance.organization_id else None,
        affected_count=affected_count,
        delegator_user_ids=affected_user_ids[:_DELEGATION_UNSUPPRESS_WARN_THRESHOLD],
        is_expired=instance.is_expired() if instance.created_at else False,
    )
