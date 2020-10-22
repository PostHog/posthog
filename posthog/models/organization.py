from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.db import models, transaction
from django.dispatch import receiver
from django.utils import timezone

from .utils import UUIDModel, sane_repr

try:
    from ee.models.license import License
except ImportError:
    License = None  # type: ignore

try:
    from multi_tenancy.models import OrganizationBilling  # type: ignore
except ImportError:
    OrganizationBilling = None


class OrganizationManager(models.Manager):
    def bootstrap(
        self, user: Any, *, team_fields: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Tuple["Organization", "OrganizationMembership", Any]:
        """Instead of doing the legwork of creating an organization yourself, delegate the details with bootstrap."""
        from .team import Team  # Avoiding circular import

        with transaction.atomic():
            organization = Organization.objects.create(**kwargs)
            organization_membership = OrganizationMembership.objects.create(
                organization=organization, user=user, level=OrganizationMembership.Level.ADMIN
            )
            team = Team.objects.create(organization=organization, **(team_fields or {}))
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
    def billing_plan(self) -> Optional[str]:
        # If the EE folder is missing no features are available
        if not settings.EE_AVAILABLE:
            return None
        # If we're on Cloud, grab the organization's price
        if OrganizationBilling is not None:
            try:
                return OrganizationBilling.objects.get(organization_id=self.id).get_plan_key()
            except OrganizationBilling.DoesNotExist:
                return None
        # Otherwise, try to find a valid license on this instance
        if License is not None:
            license = License.objects.filter(valid_until__gte=timezone.now()).first()
            if license:
                return license.plan
        return None

    @property
    def available_features(self) -> List[str]:
        plan = self.billing_plan
        if not plan:
            return []
        if plan not in License.PLANS:
            return []
        return License.PLANS[plan]

    def is_feature_available(self, feature: str) -> bool:
        return feature in self.available_features

    def __str__(self):
        return self.name

    __repr__ = sane_repr("name")


class OrganizationMembership(UUIDModel):
    class Level(models.IntegerChoices):
        MEMBER = 1, "member"
        ADMIN = 8, "administrator"

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
            models.UniqueConstraint(fields=["organization_id", "user_id"], name="unique_organization_membership")
        ]

    def __str__(self):
        return str(self.Level(self.level))

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
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    def validate(self, *, user: Optional[Any], email: Optional[str] = None) -> None:
        if not email:
            assert user is not None, "Either user or email must be provided!"
            email = user.email
        if email != self.target_email:
            raise ValueError("Invite is not intended for this email.")
        if OrganizationMembership.objects.filter(organization=self.organization, user=user).exists():
            raise ValueError("User already is a member of the organization.")
        if OrganizationMembership.objects.filter(
            organization=self.organization, user__email=self.target_email
        ).exists():
            raise ValueError("Target email already is a member of the organization.")

    def use(self, user: Any, *, prevalidated: bool = False) -> None:
        if not prevalidated:
            self.validate(user=user)
        self.organization.members.add(user)
        if user.current_organization is None:
            user.current_organization = self.organization
            user.current_team = user.current_organization.teams.first()
            user.save()
        self.delete()

    def __str__(self):
        return f"{settings.SITE_URL}/signup/{self.id}/"

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
