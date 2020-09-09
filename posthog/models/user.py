from typing import List, Optional, Union

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.dispatch import receiver
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _
from rest_framework.fields import BooleanField

from .organization import MembershipLevel, Organization, OrganizationMembership
from .team import Team
from .utils import generate_random_token

EE_MISSING = False
MULTI_TENANCY_MISSING = False
try:
    from ee.models.license import License
except ImportError:
    EE_MISSING = True

try:
    from multi_tenancy.models import TeamBilling  # type: ignore
except ImportError:
    TeamBilling = False
    MULTI_TENANCY_MISSING = True


def is_email_restricted_from_signup(email: str) -> bool:
    if not hasattr(settings, "RESTRICT_SIGNUPS"):
        return False

    restricted_signups: Union[str, bool] = settings.RESTRICT_SIGNUPS
    if restricted_signups is False:
        return False

    domain = email.rsplit("@", 1)[1]
    whitelisted_domains = str(settings.RESTRICT_SIGNUPS).split(",")
    if domain in whitelisted_domains:
        return False

    return True


class UserManager(BaseUserManager):
    """Define a model manager for User model with no username field."""

    use_in_migrations = True

    def _create_user(self, email: Optional[str], password: str, **extra_fields):
        """Create and save a User with the given email and password."""
        if email is None:
            raise ValueError("The given email must be set")

        email = self.normalize_email(email)
        if is_email_restricted_from_signup(email):
            raise ValueError("Can't sign up with this email")

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save()
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular User with the given email and password."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("distinct_id", generate_random_token())
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        """Create and save a SuperUser with the given email and password."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    DEFAULT = "default"
    TOOLBAR = "toolbar"
    TOOLBAR_CHOICES = [
        (DEFAULT, DEFAULT),
        (TOOLBAR, TOOLBAR),
    ]

    username = None  # type: ignore
    current_organization = models.ForeignKey("posthog.Organization", models.SET_NULL, null=True)
    current_team = models.ForeignKey("posthog.Team", models.SET_NULL, null=True)
    email = models.EmailField(_("email address"), unique=True)
    temporary_token: models.CharField = models.CharField(max_length=200, null=True, blank=True, unique=True)
    distinct_id: models.CharField = models.CharField(max_length=200, null=True, blank=True, unique=True)
    email_opt_in: models.BooleanField = models.BooleanField(default=False, null=True, blank=True)
    anonymize_data: models.BooleanField = models.BooleanField(default=False, null=True, blank=True)
    toolbar_mode: models.CharField = models.CharField(
        max_length=200, null=True, blank=True, choices=TOOLBAR_CHOICES, default=TOOLBAR
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: List[str] = []

    objects: UserManager = UserManager()  # type: ignore

    def feature_available(self, feature: str) -> bool:
        return feature in self.available_features

    @property
    def ee_available(self) -> bool:
        return not EE_MISSING

    @property
    def billing_plan(self) -> Optional[str]:
        # If the EE folder is missing no features are available
        if EE_MISSING:
            return None

        # If we're on multi-tenancy grab the team's price
        if not MULTI_TENANCY_MISSING:
            try:
                return TeamBilling.objects.get(team=self.team).price_id
            except TeamBilling.DoesNotExist:
                return None
        # Otherwise, try to find a valid license on this instance
        license = License.objects.filter(valid_until__gte=now()).first()
        if license:
            return license.plan
        return None

    @property
    def available_features(self) -> List[str]:
        user_plan = self.billing_plan
        if not user_plan:
            return []
        if user_plan not in License.PLANS:
            return []
        return License.PLANS[user_plan]

    @property
    def teams(self) -> List[Team]:
        return Team.objects.filter(organization__in=self.organizations.all())

    @property
    def organization(self) -> Organization:
        return self.current_organization

    @property
    def team(self) -> Team:
        return self.current_team

    def _ensure_organization_and_team(self) -> None:
        save = False
        if self.current_organization is None:
            try:
                # set any first organization user belongs to as current, if there wasn't any set before for some reason
                self.current_organization = self.organizations.first()
                # migrate from old Team-based approach, where there's no organization yet
                if self.current_organization is None:
                    team = self.teams_deprecated_relationship.get()
                    self.current_organization = Organization.objects.create(name=team.name)
                    team.organization = self.current_organization
                    team.save()
                    # migrated users become admins
                    OrganizationMembership.objects.create(
                        organization=self.current_organization, user=self, level=MembershipLevel.ADMIN
                    )
            except ValueError:
                pass  # ignoring as this happens before server has fully instantiated
            else:
                save = True
        if self.current_team is None and self.current_organization is not None:
            self.current_team = self.current_organization.teams.get()
            save = True
        if save:
            self.save()


@receiver(models.signals.post_init, sender=User)
def ensure_organization_and_team(sender, instance: User, **kwargs):
    instance._ensure_organization_and_team()
