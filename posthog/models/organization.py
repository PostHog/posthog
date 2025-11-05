import sys
from datetime import datetime, timedelta
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
import dateutil.parser
from rest_framework import exceptions

from posthog.cloud_utils import is_cloud
from posthog.constants import INVITE_DAYS_VALIDITY, MAX_SLUG_LENGTH, AvailableFeature
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import LowercaseSlugField, UUIDTModel, create_with_slug, sane_repr

if TYPE_CHECKING:
    from posthog.models import Team, User

    from ee.billing.quota_limiting import QuotaResource


logger = structlog.get_logger(__name__)


class OrganizationUsageResource(TypedDict):
    usage: int | None
    limit: int | None
    todays_usage: int | None


# The "usage" field is essentially cached info from the Billing Service to be used for visual reporting to the user
# as well as for enforcing limits.
class OrganizationUsageInfo(TypedDict):
    events: OrganizationUsageResource | None
    exceptions: OrganizationUsageResource | None
    recordings: OrganizationUsageResource | None
    survey_responses: OrganizationUsageResource | None
    rows_synced: OrganizationUsageResource | None
    cdp_trigger_events: OrganizationUsageResource | None
    rows_exported: OrganizationUsageResource | None
    feature_flag_requests: OrganizationUsageResource | None
    api_queries_read_bytes: OrganizationUsageResource | None
    llm_events: OrganizationUsageResource | None
    period: list[str] | None


class ProductFeature(TypedDict):
    key: str
    name: str
    description: str
    unit: str | None
    limit: int | None
    note: str | None
    is_plan_default: bool


class OrganizationManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any):
        return create_with_slug(super().create, *args, **kwargs)

    def bootstrap(
        self,
        user: Optional["User"],
        *,
        team_fields: dict[str, Any] | None = None,
        **kwargs,
    ) -> tuple["Organization", Optional["OrganizationMembership"], "Team"]:
        """Instead of doing the legwork of creating an organization yourself, delegate the details with bootstrap."""
        from .project import Project  # Avoiding circular import

        with transaction.atomic(using=self.db):
            organization = Organization.objects.create(**kwargs)
            _, team = Project.objects.create_with_team(
                initiating_user=user, organization=organization, team_fields=team_fields
            )
            organization_membership: OrganizationMembership | None = None
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


def default_anonymize_ips():
    """Default to True for EU cloud deployments to comply with stricter privacy requirements"""
    return getattr(settings, "CLOUD_DEPLOYMENT", None) == "EU"


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
    default_anonymize_ips = models.BooleanField(
        default=False,
        help_text="Default setting for 'Discard client IP data' for new projects in this organization.",
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
    def _billing_plan_details(self) -> tuple[str | None, str | None]:
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

    def get_available_feature(self, feature: Union[AvailableFeature, str]) -> ProductFeature | None:
        return next(
            filter(lambda f: f and f.get("key") == feature, self.available_product_features or []),
            None,
        )

    def is_feature_available(self, feature: Union[AvailableFeature, str]) -> bool:
        return bool(self.get_available_feature(feature))

    def limit_product_until_end_of_billing_cycle(self, resource: "QuotaResource") -> None:
        """
        Limit a resource for all teams of this organization until the end of the current billing cycle.
        Updates the organization's usage data with the quota_limited_until timestamp.
        """
        from ee.billing.quota_limiting import (
            QuotaLimitingCaches,
            add_limited_team_tokens,
            update_organization_usage_fields,
        )

        billing_period = self.current_billing_period

        if billing_period:
            _start, end = billing_period
            billing_period_end_timestamp = int(end.timestamp())

            team_tokens: dict[str, int] = {
                t: billing_period_end_timestamp for t in self.teams.values_list("api_token", flat=True) if t
            }
            add_limited_team_tokens(resource, team_tokens, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)

            update_organization_usage_fields(
                self,
                resource,
                {"quota_limited_until": billing_period_end_timestamp, "quota_limiting_suspended_until": None},
            )
        else:
            raise RuntimeError("Cannot limit without having a billing period")

    def unlimit_product(self, resource: "QuotaResource") -> None:
        """
        Remove limiting for a resource for all teams of this organization.
        Removes teams from the limiting cache and clears quota_limited_until from usage data.
        """
        from ee.billing.quota_limiting import (
            QuotaLimitingCaches,
            remove_limited_team_tokens,
            update_organization_usage_fields,
        )

        team_tokens: list[str] = [t for t in self.teams.values_list("api_token", flat=True) if t]
        remove_limited_team_tokens(resource, team_tokens, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)

        if self.usage and resource.value in self.usage:
            update_organization_usage_fields(
                self, resource, {"quota_limited_until": None, "quota_limiting_suspended_until": None}
            )

    def get_limited_products(self) -> dict[str, dict[str, Any]]:
        """
        Returns information about which products are currently limited for this organization.

        Uses Redis pipelining to efficiently check all team tokens for all resources in a single batch.
        Returns both Redis state (source of truth) and usage field data (which may be out of sync).

        Returns a dict mapping resource names to their limiting status:
        {
            "events": {
                "is_limited_in_redis": True,
                "redis_quota_limited_until": 1234567890,
                "limited_teams": ["team_token_1", "team_token_2"],
                "usage_quota_limited_until": 1234567890,
                "usage_quota_limiting_suspended_until": None
            },
            "recordings": {
                "is_limited_in_redis": False,
                "redis_quota_limited_until": None,
                "limited_teams": [],
                "usage_quota_limited_until": None,
                "usage_quota_limiting_suspended_until": None
            },
            ...
        }
        """
        from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, get_client

        team_tokens = [t for t in self.teams.values_list("api_token", flat=True) if t]

        result: dict[str, dict[str, Any]] = {}
        for resource in QuotaResource:
            usage_quota_limited_until = None
            usage_quota_limiting_suspended_until = None

            if self.usage and resource.value in self.usage:
                resource_usage = self.usage[resource.value]
                usage_quota_limited_until = resource_usage.get("quota_limited_until")
                usage_quota_limiting_suspended_until = resource_usage.get("quota_limiting_suspended_until")

            result[resource.value] = {
                "is_limited_in_redis": False,
                "redis_quota_limited_until": None,
                "limited_teams": [],
                "usage_quota_limited_until": usage_quota_limited_until,
                "usage_quota_limiting_suspended_until": usage_quota_limiting_suspended_until,
            }

        if not team_tokens:
            return result

        redis_client = get_client()
        now = timezone.now().timestamp()

        pipe = redis_client.pipeline()
        checks: list[tuple[QuotaResource, str]] = []

        for resource in QuotaResource:
            cache_key = f"{QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY.value}{resource.value}"
            for token in team_tokens:
                pipe.zscore(cache_key, token)
                checks.append((resource, token))

        scores = pipe.execute()

        for (resource, token), score in zip(checks, scores):
            if score is not None and score >= now:
                result[resource.value]["is_limited_in_redis"] = True
                result[resource.value]["limited_teams"].append(token)
                current_max = result[resource.value]["redis_quota_limited_until"]
                if current_max is None or score > current_max:
                    result[resource.value]["redis_quota_limited_until"] = int(score)

        return result

    @property
    def current_billing_period(self) -> tuple[datetime, datetime] | None:
        """
        Returns the current billing period as a tuple of (start, end).
        Returns None if usage data is not available or period is not set.
        """
        if not self.usage or "period" not in self.usage:
            return None

        try:
            period = self.usage["period"]
            if not period or len(period) < 2:
                return None

            start = dateutil.parser.isoparse(period[0])
            end = dateutil.parser.isoparse(period[1])
            return (start, end)
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Failed to parse billing period for organization {self.id}: {e}")
            return None

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
        new_level: Level | None = None,
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
