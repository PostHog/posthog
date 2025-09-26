from collections.abc import Callable
from functools import cached_property
from typing import Any, Optional, TypedDict

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import ValidationError

from posthog.cloud_utils import get_cached_instance_license, is_cloud
from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception
from posthog.helpers.email_utils import EmailNormalizer
from posthog.settings import INSTANCE_TAG, SITE_URL
from posthog.utils import get_instance_realm

from .organization import Organization, OrganizationMembership
from .personal_api_key import PersonalAPIKey, hash_key_value
from .team import Team
from .utils import UUIDTClassicModel, generate_random_token, sane_repr


class Notifications(TypedDict, total=False):
    plugin_disabled: bool
    error_tracking_issue_assigned: bool
    discussions_mentioned: bool
    project_weekly_digest_disabled: dict[str, Any]  # Maps project ID to disabled status, str is the team_id as a string
    all_weekly_digest_disabled: bool


NOTIFICATION_DEFAULTS: Notifications = {
    "plugin_disabled": True,  # Catch all for any Pipeline destination issue (plugins, hog functions, batch exports)
    "error_tracking_issue_assigned": True,  # Error tracking issue assignment
    "discussions_mentioned": True,  # Mentions in comments enabled by default
    "project_weekly_digest_disabled": {},  # Empty dict by default - no projects disabled
    "all_weekly_digest_disabled": False,  # Weekly digests enabled by default
}

# We don't ned the following attributes in most cases, so we defer them by default
DEFERED_ATTRS = ["requested_password_reset_at"]

ROLE_CHOICES = (
    ("engineering", "Engineering"),
    ("data", "Data"),
    ("product", "Product Management"),
    ("founder", "Founder"),
    ("leadership", "Leadership"),
    ("marketing", "Marketing"),
    ("sales", "Sales / Success"),
    ("other", "Other"),
)


class UserManager(BaseUserManager):
    """Define a model manager for User model with no username field."""

    def get_queryset(self):
        return super().get_queryset().defer(*DEFERED_ATTRS)

    model: type["User"]

    use_in_migrations = True

    def create_user(self, email: str, password: Optional[str], first_name: str, **extra_fields) -> "User":
        """Create and save a User with the given email and password."""
        if email is None:
            raise ValueError("Email must be provided!")
        email = EmailNormalizer.normalize(email)
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
        organization_fields: Optional[dict[str, Any]] = None,
        team_fields: Optional[dict[str, Any]] = None,
        create_team: Optional[Callable[["Organization", "User"], "Team"]] = None,
        is_staff: bool = False,
        **user_fields,
    ) -> tuple["Organization", "Team", "User"]:
        """Instead of doing the legwork of creating a user from scratch, delegate the details with bootstrap."""
        with transaction.atomic():
            organization_fields = organization_fields or {}
            organization_fields.setdefault("name", organization_name)
            organization = Organization.objects.create(**organization_fields)
            user = self.create_user(
                email=email,
                password=password,
                first_name=first_name,
                is_staff=is_staff,
                **user_fields,
            )
            if create_team:
                team = create_team(organization, user)
            else:
                team = Team.objects.create_with_data(
                    initiating_user=user, organization=organization, **(team_fields or {})
                )
            user.join(organization=organization, level=OrganizationMembership.Level.OWNER)
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
                PersonalAPIKey.objects.select_related("user")
                .filter(user__is_active=True)
                .get(secure_value=hash_key_value(key_value))
            )
        except PersonalAPIKey.DoesNotExist:
            return None
        else:
            personal_api_key.last_used_at = timezone.now()
            personal_api_key.save()
            return personal_api_key.user


def events_column_config_default() -> dict[str, Any]:
    return {"active": "DEFAULT"}


class ThemeMode(models.TextChoices):
    LIGHT = "light", "Light"
    DARK = "dark", "Dark"
    SYSTEM = "system", "System"


class User(AbstractUser, UUIDTClassicModel):
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    DISABLED = "disabled"
    TOOLBAR = "toolbar"
    TOOLBAR_CHOICES = [(DISABLED, DISABLED), (TOOLBAR, TOOLBAR)]

    current_organization = models.ForeignKey(
        "posthog.Organization",
        models.SET_NULL,
        null=True,
        related_name="users_currently+",
    )
    current_team = models.ForeignKey("posthog.Team", models.SET_NULL, null=True, related_name="teams_currently+")
    email = models.EmailField(_("email address"), unique=True)
    pending_email = models.EmailField(_("pending email address awaiting verification"), null=True, blank=True)
    temporary_token = models.CharField(max_length=200, null=True, blank=True, unique=True)
    distinct_id = models.CharField(max_length=200, null=True, blank=True, unique=True)
    is_email_verified = models.BooleanField(null=True, blank=True)
    requested_password_reset_at = models.DateTimeField(null=True, blank=True)
    has_seen_product_intro_for = models.JSONField(null=True, blank=True)
    strapi_id = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Unselect this to temporarily disable an account."),
    )
    role_at_organization = models.CharField(max_length=64, choices=ROLE_CHOICES, null=True, blank=True)
    # Preferences / configuration options

    theme_mode = models.CharField(max_length=20, null=True, blank=True, choices=ThemeMode.choices)
    # These override the notification settings
    partial_notification_settings = models.JSONField(null=True, blank=True)
    anonymize_data = models.BooleanField(default=False, null=True, blank=True)
    toolbar_mode = models.CharField(max_length=200, null=True, blank=True, choices=TOOLBAR_CHOICES, default=TOOLBAR)
    hedgehog_config = models.JSONField(null=True, blank=True)

    # DEPRECATED
    events_column_config = models.JSONField(default=events_column_config_default)
    # DEPRECATED - Most emails are done via 3rd parties and we use their opt/in out tooling
    email_opt_in = models.BooleanField(default=False, null=True, blank=True)

    # Remove unused attributes from `AbstractUser`
    username = None

    objects: UserManager = UserManager()

    @property
    def is_superuser(self) -> bool:
        return self.is_staff

    @cached_property
    def teams(self):
        """
        All teams the user has access to on any organization, taking into account project based permissioning
        """
        teams = Team.objects.filter(organization__members=self)
        org_available_product_features = (
            Organization.objects.filter(members=self).values_list("available_product_features", flat=True).first()
        )
        if org_available_product_features and len(org_available_product_features) > 0:
            org_available_product_feature_keys = [feature["key"] for feature in org_available_product_features]
            if AvailableFeature.ADVANCED_PERMISSIONS in org_available_product_feature_keys:
                try:
                    from ee.models.rbac.access_control import AccessControl
                except ImportError:
                    pass
                else:
                    # Get organization memberships for this user to check access levels
                    org_memberships = OrganizationMembership.objects.filter(user=self).select_related("organization")

                    # Get teams that are private (have access_level="none" restrictions)
                    private_team_ids = set(
                        AccessControl.objects.filter(
                            resource="project", access_level="none", organization_member=None, role=None
                        ).values_list("team_id", flat=True)
                    )

                    # Get teams where user has explicit access
                    accessible_private_team_ids = set(
                        AccessControl.objects.filter(
                            resource="project",
                            access_level__in=["member", "admin"],
                            organization_member__in=[membership.id for membership in org_memberships],
                        ).values_list("team_id", flat=True)
                    )

                    # Get teams where user has role-based access
                    try:
                        from ee.models.rbac.role import RoleMembership

                        user_roles = RoleMembership.objects.filter(
                            user=self, organization_member__in=[membership.id for membership in org_memberships]
                        ).values_list("role_id", flat=True)

                        role_accessible_team_ids = set(
                            AccessControl.objects.filter(
                                resource="project", access_level__in=["member", "admin"], role__in=user_roles
                            ).values_list("team_id", flat=True)
                        )
                    except ImportError:
                        role_accessible_team_ids = set()

                    # Get organizations where user is admin or owner (have implicit access to all teams)
                    organizations_where_user_is_admin = OrganizationMembership.objects.filter(
                        user=self, level__gte=OrganizationMembership.Level.ADMIN
                    ).values_list("organization_id", flat=True)

                    # Filter teams to include:
                    # - Teams that are not private (not in private_team_ids) OR
                    # - Teams where user has explicit access OR
                    # - Teams where user has role-based access OR
                    # - Teams in organizations where user is admin/owner
                    accessible_team_ids = accessible_private_team_ids | role_accessible_team_ids

                    # Build the list of all accessible team IDs
                    all_accessible_team_ids = set()

                    # Add teams from organizations where user is admin
                    admin_teams = Team.objects.filter(
                        organization__pk__in=organizations_where_user_is_admin, organization__members=self
                    ).values_list("pk", flat=True)
                    all_accessible_team_ids.update(admin_teams)

                    # Add teams that are not private
                    non_private_teams = (
                        Team.objects.filter(organization__members=self)
                        .exclude(pk__in=private_team_ids)
                        .values_list("pk", flat=True)
                    )
                    all_accessible_team_ids.update(non_private_teams)

                    # Add teams with explicit access
                    all_accessible_team_ids.update(accessible_team_ids)

                    # Apply the final filter
                    teams = teams.filter(pk__in=all_accessible_team_ids)

        return teams.order_by("id")

    @cached_property
    def organization(self) -> Optional[Organization]:
        if self.current_organization is None:
            if self.current_team is not None:
                self.current_organization_id = self.current_team.organization_id
            self.current_organization = self.organizations.first()
            if self.current_organization is not None:
                self.save(update_fields=["current_organization"])
        return self.current_organization

    @cached_property
    def team(self) -> Optional[Team]:
        if self.current_team is None and self.organization is not None:
            self.current_team = self.teams.filter(organization=self.current_organization).first()
            if self.current_team:
                self.save(update_fields=["current_team"])
        return self.current_team

    def join(
        self,
        *,
        organization: Organization,
        level: OrganizationMembership.Level = OrganizationMembership.Level.MEMBER,
    ) -> OrganizationMembership:
        with transaction.atomic():
            membership = OrganizationMembership.objects.create(user=self, organization=organization, level=level)

            self.current_organization = organization
            if not organization.is_feature_available(AvailableFeature.ADVANCED_PERMISSIONS):
                # If project access control is NOT applicable, simply prefer open projects just in case
                self.current_team = organization.teams.order_by("id").first()
            else:
                from posthog.rbac.user_access_control import UserAccessControl

                uac = UserAccessControl(user=self, organization_id=str(organization.id))
                self.current_team = (
                    uac.filter_queryset_by_access_level(organization.teams.all(), include_all_if_admin=True)
                    .order_by("id")
                    .first()
                )
            self.save()

        # Auto-assign default role if configured
        if organization.default_role_id:
            try:
                from ee.models import RoleMembership

                RoleMembership.objects.create(
                    role_id=organization.default_role_id, user=self, organization_member=membership
                )
            except Exception as e:
                capture_exception(
                    e,
                    {
                        "organization_id": organization.id,
                        "role_id": organization.default_role_id,
                        "context": "default_role_assignment",
                        "tag": "platform-features",
                    },
                )

        self.update_billing_organization_users(organization)
        return membership

    @property
    def notification_settings(self) -> Notifications:
        return {
            **NOTIFICATION_DEFAULTS,
            **(self.partial_notification_settings if self.partial_notification_settings else {}),
        }

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
                self.team = self.current_team  # Update cached property
                self.save()
        self.update_billing_organization_users(organization)

    def update_billing_organization_users(self, organization: Organization) -> None:
        from ee.billing.billing_manager import BillingManager  # avoid circular import

        if is_cloud() and get_cached_instance_license() is not None:
            BillingManager(get_cached_instance_license()).update_billing_organization_users(organization)

    def get_analytics_metadata(self):
        team_member_count_all: int = (
            OrganizationMembership.objects.filter(organization__in=self.organizations.all())
            .values("user_id")
            .distinct()
            .count()
        )

        current_organization_membership = None
        if self.organization:
            current_organization_membership = self.organization.memberships.filter(user=self).first()

        project_setup_complete = False
        if self.team and self.team.completed_snippet_onboarding and self.team.ingested_event:
            project_setup_complete = True

        return {
            "realm": get_instance_realm(),
            "anonymize_data": self.anonymize_data,
            "email": self.email if not self.anonymize_data else None,
            "is_signed_up": True,
            "organization_count": self.organization_memberships.count(),
            "project_count": self.teams.count(),
            "team_member_count_all": team_member_count_all,
            "completed_onboarding_once": self.teams.filter(
                completed_snippet_onboarding=True, ingested_event=True
            ).exists(),  # has completed the onboarding at least for one project
            # properties dependent on current project / org below
            "organization_id": str(self.organization.id) if self.organization else None,
            "current_organization_membership_level": (
                current_organization_membership.level if current_organization_membership else None
            ),
            "project_id": str(self.team.uuid) if self.team else None,
            "project_setup_complete": project_setup_complete,
            "joined_at": self.date_joined,
            "has_password_set": self.has_usable_password(),
            "has_social_auth": self.social_auth.exists(),
            "social_providers": list(self.social_auth.values_list("provider", flat=True)),
            "instance_url": SITE_URL,
            "instance_tag": INSTANCE_TAG,
            "is_email_verified": self.is_email_verified,
            "has_seen_product_intro_for": self.has_seen_product_intro_for,
            "strapi_id": self.strapi_id,
        }

    __repr__ = sane_repr("email", "first_name", "distinct_id")
