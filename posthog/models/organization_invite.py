from datetime import timedelta
from typing import TYPE_CHECKING, Optional

from django.db import models
from django.utils import timezone

import structlog
from rest_framework import exceptions

from posthog.constants import INVITE_DAYS_VALIDITY
from posthog.email import is_email_available
from posthog.helpers.email_utils import EmailNormalizer, EmailValidationHelper
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.utils import UUIDTModel, sane_repr
from posthog.utils import absolute_uri

from ee.models.rbac.access_control import AccessControl

if TYPE_CHECKING:
    from posthog.models import User


logger = structlog.get_logger(__name__)


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
        default=OrganizationMembership.Level.MEMBER, choices=OrganizationMembership.Level.choices
    )
    private_project_access = models.JSONField(
        default=list,
        null=True,
        blank=True,
        help_text="List of team IDs and corresponding access levels to private projects.",
        validators=[validate_private_project_access],
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
        user.join(organization=self.organization, level=self.level)

        for item in self.private_project_access or []:
            try:
                team: Team = self.organization.teams.get(id=item["id"])
                parent_membership = OrganizationMembership.objects.get(
                    organization=self.organization,
                    user=user,
                )
            except self.organization.teams.model.DoesNotExist:
                # if the team doesn't exist, it was probably deleted. We can still continue with the invite.
                continue

            AccessControl.objects.create(
                team=team,
                resource="project",
                resource_id=str(team.id),
                organization_member=parent_membership,
                access_level=item["level"],
            )

        if is_email_available(with_absolute_urls=True) and self.organization.is_member_join_email_enabled:
            from posthog.tasks.email import send_member_join

            send_member_join.apply_async(
                kwargs={
                    "invitee_uuid": user.uuid,
                    "organization_id": self.organization_id,
                }
            )
        OrganizationInvite.objects.filter(
            organization=self.organization, target_email__iexact=self.target_email
        ).delete()

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
