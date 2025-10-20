import sys
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Optional, TypedDict, Union

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.cache import cache
from django.db import models, transaction
from django.db.models.query import QuerySet
from django.db.models.query_utils import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

import structlog
from rest_framework import exceptions

from posthog.cloud_utils import is_cloud
from posthog.constants import INVITE_DAYS_VALIDITY, MAX_SLUG_LENGTH, AvailableFeature
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import LowercaseSlugField, UUIDTModel, create_with_slug, sane_repr

if TYPE_CHECKING:
    from posthog.models import Team, User


logger = structlog.get_logger(__name__)


class OrganizationUsageResource(TypedDict):
    usage: Optional[int]
    limit: Optional[int]
    todays_usage: Optional[int]


# The "usage" field is essentially cached info from the Billing Service to be used for visual reporting to the user
# as well as for enforcing limits.
class OrganizationUsageInfo(TypedDict):
    events: Optional[OrganizationUsageResource]
    exceptions: Optional[OrganizationUsageResource]
    recordings: Optional[OrganizationUsageResource]
    survey_responses: Optional[OrganizationUsageResource]
    rows_synced: Optional[OrganizationUsageResource]
    cdp_trigger_events: Optional[OrganizationUsageResource]
    rows_exported: Optional[OrganizationUsageResource]
    feature_flag_requests: Optional[OrganizationUsageResource]
    api_queries_read_bytes: Optional[OrganizationUsageResource]
    llm_events: Optional[OrganizationUsageResource]
    period: Optional[list[str]]


class ProductFeature(TypedDict):
    key: str
    name: str
    description: str
    unit: Optional[str]
    limit: Optional[int]
    note: Optional[str]
    is_plan_default: bool


class OrganizationManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any):
        return create_with_slug(super().create, *args, **kwargs)

    def bootstrap(
        self,
        user: Optional["User"],
        *,
        team_fields: Optional[dict[str, Any]] = None,
        **kwargs,
    ) -> tuple["Organization", Optional["OrganizationMembership"], "Team"]:
        """Instead of doing the legwork of creating an organization yourself, delegate the details with bootstrap."""
        from .project import Project  # Avoiding circular import

        with transaction.atomic(using=self.db):
            organization = Organization.objects.create(**kwargs)
            _, team = Project.objects.create_with_team(
                initiating_user=user, organization=organization, team_fields=team_fields
            )
            organization_membership: Optional[OrganizationMembership] = None
            if user is not None:
                organization_membership = OrganizationMembership.objects.create(
                    organization=organization,
                    user=user,
                    level=OrganizationMembership.Level.OWNER,
                )
                user.current_organization = organization
                user.organization = user.current_organization  # Update cached property
                user.current_team = team
                user.team = user.current_team  # Update cached property
                user.save()

        return organization, organization_membership, team


class Organization(ModelActivityMixin, UUIDTModel):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["for_internal_metrics"],
                condition=Q(for_internal_metrics=True),
                name="single_for_internal_metrics",
            )
        ]

    class PluginsAccessLevel(models.IntegerChoices):
        # None means the organization can't use plugins at all. They're hidden. Cloud default.
        NONE = 0, "none"
        # Config means the organization can only enable/disable/configure globally managed plugins.
        # This prevents config orgs from running untrusted code, which the next levels can do.
        CONFIG = 3, "config"
        # Install means the organization has config capabilities + can install own editor/GitHub/GitLab/npm plugins.
        # The plugin repository is off limits, as repository installations are managed by root orgs to avoid confusion.
        INSTALL = 6, "install"
        # Root means the organization has unrestricted plugins access on the instance. Self-hosted default.
        # This includes installing plugins from the repository and managing plugin installations for all other orgs.
        ROOT = 9, "root"

    class DefaultExperimentStatsMethod(models.TextChoices):
        BAYESIAN = "bayesian", "Bayesian"
        FREQUENTIST = "frequentist", "Frequentist"

    members = models.ManyToManyField(
        "posthog.User",
        through="posthog.OrganizationMembership",
        related_name="organizations",
        related_query_name="organization",
    )

    # General settings
    name = models.CharField(max_length=64)
    slug: LowercaseSlugField = LowercaseSlugField(unique=True, max_length=MAX_SLUG_LENGTH)
    logo_media = models.ForeignKey("posthog.UploadedMedia", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Security / management settings
    session_cookie_age = models.IntegerField(
        null=True,
        blank=True,
        help_text="Custom session cookie age in seconds. If not set, the global setting SESSION_COOKIE_AGE will be used.",
    )
    is_member_join_email_enabled = models.BooleanField(default=True)
    is_ai_data_processing_approved = models.BooleanField(null=True, blank=True)
    enforce_2fa = models.BooleanField(null=True, blank=True)
    members_can_invite = models.BooleanField(default=True, null=True, blank=True)
    members_can_use_personal_api_keys = models.BooleanField(default=True)
    allow_publicly_shared_resources = models.BooleanField(default=True)
    default_role = models.ForeignKey(
        "ee.Role",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_organizations",
        help_text="Role automatically assigned to new members joining the organization",
    )

    # Misc
    plugins_access_level = models.PositiveSmallIntegerField(
        default=PluginsAccessLevel.CONFIG,
        choices=PluginsAccessLevel.choices,
    )
    for_internal_metrics = models.BooleanField(default=False)
    default_experiment_stats_method = models.CharField(
        max_length=20,
        choices=DefaultExperimentStatsMethod.choices,
        default=DefaultExperimentStatsMethod.BAYESIAN,
        help_text="Default statistical method for new experiments in this organization.",
        null=True,
        blank=True,
    )
    is_hipaa = models.BooleanField(default=False, null=True, blank=True)

    ## Managed by Billing
    customer_id = models.CharField(max_length=200, null=True, blank=True)

    # looking for feature? check: is_feature_available, get_available_feature
    available_product_features = ArrayField(models.JSONField(blank=False), null=True, blank=True)
    # Managed by Billing, cached here for usage controls
    # Like {
    #   'events': { 'usage': 10000, 'limit': 20000, 'todays_usage': 1000 },
    #   'recordings': { 'usage': 10000, 'limit': 20000, 'todays_usage': 1000 }
    #   'feature_flags_requests': { 'usage': 10000, 'limit': 20000, 'todays_usage': 1000 }
    #   'api_queries_read_bytes': { 'usage': 123456789, 'limit': 1000000000000, 'todays_usage': 1234 }
    #   'period': ['2021-01-01', '2021-01-31']
    # }
    # Also currently indicates if the organization is on billing V2 or not
    usage = models.JSONField(null=True, blank=True)
    never_drop_data = models.BooleanField(default=False, null=True, blank=True)
    # Scoring levels defined in billing::customer::TrustScores
    customer_trust_scores = models.JSONField(default=dict, null=True, blank=True)

    # DEPRECATED attributes (should be removed on next major version)
    setup_section_2_completed = models.BooleanField(default=True)
    personalization = models.JSONField(default=dict, null=False, blank=True)
    domain_whitelist: ArrayField = ArrayField(
        models.CharField(max_length=256, blank=False), blank=True, default=list
    )  # DEPRECATED in favor of `OrganizationDomain` model; previously used to allow self-serve account creation based on social login (#5111)

    objects: OrganizationManager = OrganizationManager()

    is_platform = models.BooleanField(default=False, null=True, blank=True)

    def __str__(self):
        return self.name

    __repr__ = sane_repr("name")

    @property
    def _billing_plan_details(self) -> tuple[Optional[str], Optional[str]]:
        """
        Obtains details on the billing plan for the organization.
        Returns a tuple with (billing_plan_key, billing_realm)
        """
        try:
            from ee.models.license import License
        except ImportError:
            License = None  # type: ignore
        # Demo gets all features
        if settings.DEMO or "generate_demo_data" in sys.argv[1:2]:
            return (License.ENTERPRISE_PLAN, "demo")
        # Otherwise, try to find a valid license on this instance
        if License is not None:
            license = License.objects.first_valid()
            if license:
                return (license.plan, "ee")
        return (None, None)

    def update_available_product_features(self) -> list[ProductFeature]:
        """Updates field `available_product_features`. Does not `save()`."""
        if is_cloud() or self.usage:
            # Since billing V2 we just use the field which is updated when the billing service is called
            return self.available_product_features or []

        try:
            from ee.models.license import License
        except ImportError:
            self.available_product_features = []
            return []

        self.available_product_features = []

        # Self hosted legacy license so we just sync the license features
        # Demo gets all features
        if settings.DEMO or "generate_demo_data" in sys.argv[1:2]:
            features = License.PLANS.get(License.ENTERPRISE_PLAN, [])
            self.available_product_features = [
                {"key": feature, "name": " ".join(feature.split(" ")).capitalize()} for feature in features
            ]
        else:
            # Otherwise, try to find a valid license on this instance
            license = License.objects.first_valid()
            if license:
                features = License.PLANS.get(License.ENTERPRISE_PLAN, [])
                self.available_product_features = [
                    {"key": feature, "name": " ".join(feature.split(" ")).capitalize()} for feature in features
                ]

        return self.available_product_features

    def get_available_feature(self, feature: Union[AvailableFeature, str]) -> Optional[ProductFeature]:
        return next(
            filter(lambda f: f and f.get("key") == feature, self.available_product_features or []),
            None,
        )

    def is_feature_available(self, feature: Union[AvailableFeature, str]) -> bool:
        return bool(self.get_available_feature(feature))

    @property
    def active_invites(self) -> QuerySet:
        return self.invites.filter(created_at__gte=timezone.now() - timedelta(days=INVITE_DAYS_VALIDITY))

    def get_analytics_metadata(self):
        return {
            "member_count": self.members.count(),
            "project_count": self.teams.count(),
            "name": self.name,
        }


@receiver(models.signals.pre_save, sender=Organization)
def organization_about_to_be_created(sender, instance: Organization, raw, using, **kwargs):
    if instance._state.adding:
        instance.update_available_product_features()
        if not is_cloud():
            instance.plugins_access_level = Organization.PluginsAccessLevel.ROOT


class OrganizationMembership(ModelActivityMixin, UUIDTModel):
    class Level(models.IntegerChoices):
        """Keep in sync with TeamMembership.Level (only difference being projects not having an Owner)."""

        MEMBER = 1, "member"
        ADMIN = 8, "administrator"
        OWNER = 15, "owner"

    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="memberships",
        related_query_name="membership",
    )
    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="organization_memberships",
        related_query_name="organization_membership",
    )
    level = models.PositiveSmallIntegerField(default=Level.MEMBER, choices=Level.choices)
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization_id", "user_id"],
                name="unique_organization_membership",
            ),
        ]

    def __str__(self):
        return str(self.Level(self.level))

    def validate_update(
        self,
        membership_being_updated: "OrganizationMembership",
        new_level: Optional[Level] = None,
    ) -> None:
        if new_level is not None:
            if membership_being_updated.id == self.id:
                raise exceptions.PermissionDenied("You can't change your own access level.")
            if new_level == OrganizationMembership.Level.OWNER:
                if self.level != OrganizationMembership.Level.OWNER:
                    raise exceptions.PermissionDenied(
                        "You can only make another member owner if you're this organization's owner."
                    )
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

    def get_scoped_api_keys(self):
        """
        Get API keys that are scoped to this organization or its teams.
        Returns a dictionary with information about the keys.
        """
        from posthog.models.team import Team

        # Get teams that belong to this organization
        team_ids = list(Team.objects.filter(organization_id=self.organization_id).values_list("id", flat=True))

        # Find API keys scoped to either the organization or any of its teams
        # Also include keys with no scoped teams or orgs (they apply to all orgs/teams)

        personal_api_keys = PersonalAPIKey.objects.filter(user=self.user).filter(
            Q(scoped_organizations__contains=[str(self.organization_id)])
            | Q(scoped_teams__overlap=team_ids)
            | (
                (Q(scoped_organizations__isnull=True) | Q(scoped_organizations=[]))
                & (Q(scoped_teams__isnull=True) | Q(scoped_teams=[]))
            )
        )

        # Get keys with more details
        keys_data = []
        has_keys = personal_api_keys.exists()

        # Check if any keys were used in the last week
        one_week_ago = timezone.now() - timedelta(days=7)
        has_keys_active_last_week = personal_api_keys.filter(last_used_at__gte=one_week_ago).exists()

        # Get detailed information about each key
        for key in personal_api_keys:
            keys_data.append({"name": key.label, "last_used_at": key.last_used_at})

        return {
            "personal_api_keys": personal_api_keys,
            "has_keys": has_keys,
            "has_keys_active_last_week": has_keys_active_last_week,
            "keys": keys_data,
            "team_ids": team_ids,
        }

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

    __repr__ = sane_repr("organization", "user", "level")


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


@receiver(models.signals.pre_save, sender=OrganizationMembership)
def organization_membership_saved(sender: Any, instance: OrganizationMembership, **kwargs: Any) -> None:
    from posthog.event_usage import report_user_organization_membership_level_changed

    try:
        old_instance = OrganizationMembership.objects.get(id=instance.id)
        if old_instance.level != instance.level:
            # the level has been changed
            report_user_organization_membership_level_changed(
                instance.user, instance.organization, instance.level, old_instance.level
            )
    except OrganizationMembership.DoesNotExist:
        # The instance is new, or we are setting up test data
        pass


@receiver(post_save, sender=Organization)
def cache_organization_session_age(sender, instance, **kwargs):
    """Cache organization's session_cookie_age in Redis when it changes."""
    if instance.session_cookie_age is not None:
        cache.set(f"org_session_age:{instance.id}", instance.session_cookie_age)
    else:
        cache.delete(f"org_session_age:{instance.id}")
