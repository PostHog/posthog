from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models, transaction
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _

from .organization import Organization, OrganizationMembership
from .team import Team
from .utils import generate_random_token, sane_repr

MULTI_TENANCY_MISSING = False
if settings.EE_AVAILABLE:
    from ee.models.license import License

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

    def _create_user(self, email: str, password: str, **extra_fields):
        """Create and save a User with the given email and password."""
        if email is None:
            raise ValueError("The given email must be set")

        email = self.normalize_email(email)
        if is_email_restricted_from_signup(email):
            raise ValueError("Can't sign up with this email")

        extra_fields.setdefault("distinct_id", generate_random_token())

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save()
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular User with the given email and password."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
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

    def bootstrap(
        self,
        company_name: str,
        email: str,
        password: Optional[str],
        organization_fields: Optional[Dict[str, Any]] = None,
        team_fields: Optional[Dict[str, Any]] = None,
        **user_fields
    ) -> Tuple["Organization", "Team", "User"]:
        with transaction.atomic():
            organization = Organization.objects.create(name=company_name, **(organization_fields or {}))
            team = Team.objects.create_with_data(organization=organization, name=company_name, **(team_fields or {}))
            user = self.create_user(email, password, **user_fields)
            organization.members.add(user)
            team.users.add(user)
            user.current_organization = organization
            user.current_team = team
            user.save()
            return organization, team, user

    def join(
        self, organization: Organization, team: Team, email: str, password: Optional[str], **extra_fields
    ) -> "User":
        with transaction.atomic():
            user = self.create_user(email, password, **extra_fields)
            organization.members.add(user)
            team.users.add(user)
            user.current_organization = organization
            user.current_team = team
            user.save()
            return user


class User(AbstractUser):
    DEFAULT = "default"
    TOOLBAR = "toolbar"
    TOOLBAR_CHOICES = [
        (DEFAULT, DEFAULT),
        (TOOLBAR, TOOLBAR),
    ]

    username = None  # type: ignore
    current_organization = models.ForeignKey(
        "posthog.Organization", models.SET_NULL, null=True, related_name="users_currently+"
    )
    current_team = models.ForeignKey("posthog.Team", models.SET_NULL, null=True, related_name="teams_currently+")
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
        return settings.EE_AVAILABLE

    @property
    def billing_plan(self) -> Optional[str]:
        # If the EE folder is missing no features are available
        if not settings.EE_AVAILABLE:
            return None

        # If we're on multi-tenancy grab the team's price
        if not MULTI_TENANCY_MISSING:
            try:
                return TeamBilling.objects.get(team=self.team).get_price_id()
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
    def teams(self):
        return Team.objects.filter(organization__in=self.organizations.all())

    @property
    def organization(self) -> Organization:
        if self.current_organization is None:
            self.current_organization = self.organizations.get()
            self.save()
        return self.current_organization

    @property
    def team(self) -> Team:
        if self.current_team is None:
            self.current_team = self.organization.teams.get()
            self.save()
        return self.current_team

    __repr__ = sane_repr("email", "first_name", "distinct_id")
