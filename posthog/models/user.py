from typing import Any, Callable, Dict, List, Optional, Tuple

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from posthog.utils import get_instance_realm

from .organization import Organization, OrganizationMembership
from .personal_api_key import PersonalAPIKey
from .team import Team
from .utils import UUIDClassicModel, generate_random_token, sane_repr


class UserManager(BaseUserManager):
    """Define a model manager for User model with no username field."""

    use_in_migrations = True

    def create_user(self, email: str, password: Optional[str], first_name: str, **extra_fields) -> "User":
        """Create and save a User with the given email and password."""
        if email is None:
            raise ValueError("Email must be provided!")
        email = self.normalize_email(email)
        extra_fields.setdefault("distinct_id", generate_random_token())
        user = self.model(email=email, first_name=first_name, **extra_fields)
        if password is not None:
            user.set_password(password)
        user.save()
        return user

    def bootstrap(
        self,
        organization_name: str,
        email: str,
        password: Optional[str],
        first_name: str = "",
        organization_fields: Optional[Dict[str, Any]] = None,
        team_fields: Optional[Dict[str, Any]] = None,
        create_team: Optional[Callable[["Organization", "User"], "Team"]] = None,
        **user_fields,
    ) -> Tuple["Organization", "Team", "User"]:
        """Instead of doing the legwork of creating a user from scratch, delegate the details with bootstrap."""
        with transaction.atomic():
            organization_fields = organization_fields or {}
            organization_fields.setdefault("name", organization_name)
            organization = Organization.objects.create(**organization_fields)
            user = self.create_user(email=email, password=password, first_name=first_name, **user_fields)
            if create_team:
                team = create_team(organization, user)
            else:
                team = Team.objects.create_with_data(user=user, organization=organization, **(team_fields or {}))
            user.join(
                organization=organization, level=OrganizationMembership.Level.OWNER,
            )
            return organization, team, user

    def create_and_join(
        self,
        organization: Organization,
        email: str,
        password: Optional[str],
        first_name: str = "",
        level: OrganizationMembership.Level = OrganizationMembership.Level.MEMBER,
        **extra_fields,
    ) -> "User":
        with transaction.atomic():
            user = self.create_user(email=email, password=password, first_name=first_name, **extra_fields)
            user.join(organization=organization, level=level)
            return user

    def get_from_personal_api_key(self, key_value: str) -> Optional["User"]:
        try:
            personal_api_key: PersonalAPIKey = (
                PersonalAPIKey.objects.select_related("user").filter(user__is_active=True).get(value=key_value)
            )
        except PersonalAPIKey.DoesNotExist:
            return None
        else:
            personal_api_key.last_used_at = timezone.now()
            personal_api_key.save()
            return personal_api_key.user


def events_column_config_default() -> Dict[str, Any]:
    return {"active": "DEFAULT"}


class User(AbstractUser, UUIDClassicModel):
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: List[str] = []

    DISABLED = "disabled"
    TOOLBAR = "toolbar"
    TOOLBAR_CHOICES = [
        (DISABLED, DISABLED),
        (TOOLBAR, TOOLBAR),
    ]

    current_organization = models.ForeignKey(
        "posthog.Organization", models.SET_NULL, null=True, related_name="users_currently+",
    )
    current_team = models.ForeignKey("posthog.Team", models.SET_NULL, null=True, related_name="teams_currently+")
    email = models.EmailField(_("email address"), unique=True)
    temporary_token: models.CharField = models.CharField(max_length=200, null=True, blank=True, unique=True)
    distinct_id: models.CharField = models.CharField(max_length=200, null=True, blank=True, unique=True)

    # Preferences / configuration options
    email_opt_in: models.BooleanField = models.BooleanField(default=False, null=True, blank=True)
    anonymize_data: models.BooleanField = models.BooleanField(default=False, null=True, blank=True)
    toolbar_mode: models.CharField = models.CharField(
        max_length=200, null=True, blank=True, choices=TOOLBAR_CHOICES, default=TOOLBAR
    )
    events_column_config: models.JSONField = models.JSONField(default=events_column_config_default)

    # Remove unused attributes from `AbstractUser`
    username = None  # type: ignore

    objects: UserManager = UserManager()  # type: ignore

    @property
    def is_superuser(self) -> bool:  # type: ignore
        return self.is_staff

    @property
    def teams(self):
        return Team.objects.filter(organization__in=self.organizations.all())

    @property
    def organization(self) -> Optional[Organization]:
        if self.current_organization is None:
            if self.current_team is not None:
                self.current_organization_id = self.current_team.organization_id
            self.current_organization = self.organizations.first()
            self.save()
        return self.current_organization

    @property
    def team(self) -> Optional[Team]:
        if self.current_team is None and self.organization is not None:
            self.current_team = self.organization.teams.order_by("access_control", "id").first()  # Prefer open projects
            self.save()
        return self.current_team

    def join(
        self, *, organization: Organization, level: OrganizationMembership.Level = OrganizationMembership.Level.MEMBER,
    ) -> OrganizationMembership:
        with transaction.atomic():
            membership = OrganizationMembership.objects.create(user=self, organization=organization, level=level)
            self.current_organization = organization
            self.current_team = organization.teams.first()
            self.save()
            return membership

    def leave(self, *, organization: Organization) -> None:
        membership: OrganizationMembership = OrganizationMembership.objects.get(user=self, organization=organization)
        if membership.level == OrganizationMembership.Level.OWNER:
            raise ValidationError("Cannot leave the organization as its owner!")
        with transaction.atomic():
            membership.delete()
            if self.current_organization == organization:
                self.current_organization = self.organizations.first()
                self.current_team = (
                    None if self.current_organization is None else self.current_organization.teams.first()
                )
                self.save()

    def get_analytics_metadata(self):

        team_member_count_all: int = (
            OrganizationMembership.objects.filter(organization__in=self.organizations.all(),)
            .values("user_id")
            .distinct()
            .count()
        )

        project_setup_complete = False
        if self.team and self.team.completed_snippet_onboarding and self.team.ingested_event:
            project_setup_complete = True

        return {
            "realm": get_instance_realm(),
            "is_ee_available": settings.EE_AVAILABLE,
            "email_opt_in": self.email_opt_in,
            "anonymize_data": self.anonymize_data,
            "email": self.email if not self.anonymize_data else None,
            "is_signed_up": True,
            "organization_count": self.organization_memberships.count(),
            "project_count": self.teams.count(),
            "team_member_count_all": team_member_count_all,
            "completed_onboarding_once": self.teams.filter(
                completed_snippet_onboarding=True, ingested_event=True,
            ).exists(),  # has completed the onboarding at least for one project
            # properties dependent on current project / org below
            "billing_plan": self.organization.billing_plan if self.organization else None,
            "organization_id": str(self.organization.id) if self.organization else None,
            "project_id": str(self.team.uuid) if self.team else None,
            "project_setup_complete": project_setup_complete,
            "joined_at": self.date_joined,
            "has_password_set": self.has_usable_password(),
            "has_social_auth": self.social_auth.exists(),  # type: ignore
            "social_providers": list(self.social_auth.values_list("provider", flat=True)),  # type: ignore
        }

    __repr__ = sane_repr("email", "first_name", "distinct_id")
