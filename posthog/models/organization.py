from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.db import models, transaction
from django.dispatch import receiver
from django.utils import timezone
from rest_framework import exceptions

from .utils import UUIDModel, sane_repr

try:
    from ee.models.license import License
except ImportError:
    License = None  # type: ignore


class OrganizationManager(models.Manager):
    def bootstrap(
        self, user: Any, *, team_fields: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Tuple["Organization", Optional["OrganizationMembership"], Any]:
        """Instead of doing the legwork of creating an organization yourself, delegate the details with bootstrap."""
        from .team import Team  # Avoiding circular import

        with transaction.atomic():
            organization = Organization.objects.create(**kwargs)
            team = Team.objects.create(organization=organization, **(team_fields or {}))
            organization_membership: Optional[OrganizationMembership] = None
            if user is not None:
                organization_membership = OrganizationMembership.objects.create(
                    organization=organization, user=user, level=OrganizationMembership.Level.OWNER
                )
                user.current_organization = organization
                user.current_team = team
                user.save()
        return organization, organization_membership, team


class Organization(UUIDModel):
    members: models.ManyToManyField = models.ManyToManyField(
        "posthog.User",
        through="posthog.OrganizationMembership",
        related_name="organizations",
        related_query_name="organization",
    )
    name: models.CharField = models.CharField(max_length=64)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    objects = OrganizationManager()

    @property
    def _billing_plan_details(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Obtains details on the billing plan for the organization.
        Returns a tuple with (billing_plan_key, billing_realm)
        """

        # If on Cloud, grab the organization's price
        if hasattr(self, "billing"):
            if self.billing is None:  # type: ignore
                return (None, None)
            return (self.billing.get_plan_key(), "cloud")  # type: ignore

        # Otherwise, try to find a valid license on this instance
        if License is not None:
            license = License.objects.first_valid()
            if license:
                return (license.plan, "ee")
        return (None, None)

    @property
    def billing_plan(self) -> Optional[str]:
        return self._billing_plan_details[0]

    @property
    def available_features(self) -> List[str]:
        plan, realm = self._billing_plan_details
        if not plan:
            return []
        if realm == "ee":
            return License.PLANS.get(plan, [])
        return self.billing.available_features  # type: ignore

    def is_feature_available(self, feature: str) -> bool:
        return feature in self.available_features

    def __str__(self):
        return self.name

    __repr__ = sane_repr("name")


class OrganizationMembership(UUIDModel):
    class Level(models.IntegerChoices):
        MEMBER = 1, "member"
        ADMIN = 8, "administrator"
        OWNER = 15, "owner"

    organization: models.ForeignKey = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="memberships", related_query_name="membership"
    )
    user: models.ForeignKey = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="organization_memberships",
        related_query_name="organization_membership",
    )
    level: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        default=Level.MEMBER, choices=Level.choices
    )
    joined_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization_id", "user_id"], name="unique_organization_membership"),
            models.UniqueConstraint(
                fields=["organization_id"], condition=models.Q(level=15), name="only_one_owner_per_organization"
            ),
        ]

    def __str__(self):
        return str(self.Level(self.level))

    def validate_update(
        self, membership_being_updated: "OrganizationMembership", new_level: Optional[Level] = None
    ) -> None:
        if new_level is not None:
            if membership_being_updated.id == self.id:
                raise exceptions.PermissionDenied("You can't change your own access level.")
            if new_level == OrganizationMembership.Level.OWNER:
                if self.level != OrganizationMembership.Level.OWNER:
                    raise exceptions.PermissionDenied(
                        "You can only pass on organization ownership if you're its owner."
                    )
                self.level = OrganizationMembership.Level.ADMIN
                self.save()
            elif new_level > self.level:
                raise exceptions.PermissionDenied(
                    "You can only change access level of others to lower or equal to your current one."
                )
        if membership_being_updated.id != self.id:
            if membership_being_updated.organization_id != self.organization_id:
                raise exceptions.PermissionDenied("You both need to belong to the same organization.")
            if self.level < OrganizationMembership.Level.ADMIN:
                raise exceptions.PermissionDenied("You can only edit others if you are an admin.")
            if membership_being_updated.level > self.level:
                raise exceptions.PermissionDenied("You can only edit others with level lower or equal to you.")

    __repr__ = sane_repr("organization", "user", "level")


class OrganizationInvite(UUIDModel):
    organization: models.ForeignKey = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="invites", related_query_name="invite"
    )
    target_email: models.EmailField = models.EmailField(null=True, db_index=True)
    created_by: models.ForeignKey = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        related_name="organization_invites",
        related_query_name="organization_invite",
        null=True,
    )
    emailing_attempt_made: models.BooleanField = models.BooleanField(default=False)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    def validate(self, *, user: Optional[Any], email: Optional[str] = None) -> None:
        if not email:
            assert user is not None, "Either user or email must be provided!"
            email = user.email
        if self.is_expired():
            raise ValueError("This invite has expired. Please ask your admin for a new one.")
        if email != self.target_email:
            raise ValueError("This invite is intended for another email address.")
        if OrganizationMembership.objects.filter(organization=self.organization, user=user).exists():
            raise ValueError("User already is a member of the organization.")
        if OrganizationMembership.objects.filter(
            organization=self.organization, user__email=self.target_email
        ).exists():
            raise ValueError("A user with this email address already belongs to the organization.")

    def use(self, user: Any, *, prevalidated: bool = False) -> None:
        if not prevalidated:
            self.validate(user=user)
        user.join(organization=self.organization)
        OrganizationInvite.objects.filter(target_email__iexact=self.target_email).delete()

    def is_expired(self) -> bool:
        """Check if invite is older than 3 days."""
        return self.created_at < timezone.now() - timezone.timedelta(3)

    def __str__(self):
        return f"{settings.SITE_URL}/signup/{self.id}"

    __repr__ = sane_repr("organization", "target_email", "created_by")


@receiver(models.signals.pre_delete, sender=OrganizationMembership)
def ensure_organization_membership_consistency(sender, instance: OrganizationMembership, **kwargs):
    save_user = False
    if instance.user.current_organization == instance.organization:
        # reset current_organization if it's the removed organization
        instance.user.current_organization = None
        save_user = True
    if instance.user.current_team is not None and instance.user.current_team.organization == instance.organization:
        # reset current_team if it belongs to the removed organization
        instance.user.current_team = None
        save_user = True
    if save_user:
        instance.user.save()
