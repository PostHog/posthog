from collections import defaultdict
from collections.abc import Collection
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Optional, cast
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import HashIndex
from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinLengthValidator, MinValueValidator
from django.db import connection, models, transaction
from django.db.models import QuerySet
from django.db.models.fields.json import KeyTransform
from django.db.models.signals import post_delete, post_save

import pytz
import pydantic

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries, tags_context
from posthog.cloud_utils import is_cloud
from posthog.helpers.session_recording_playlist_templates import DEFAULT_PLAYLISTS
from posthog.migration_helpers import deprecate_field
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.instance_setting import get_instance_setting
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.project_secret_api_key import (
    create_project_secret_api_key_for_token,
    delete_project_secret_api_keys_for_token,
)
from posthog.models.signals import mutable_receiver, secret_api_token_rotated
from posthog.models.utils import (
    UUIDTClassicModel,
    generate_random_token_heatmap_screenshot,
    generate_random_token_project,
    generate_random_token_secret,
    mask_key_value,
    sane_repr,
    validate_rate_limit,
)
from posthog.ph_client import feature_enabled_or_false
from posthog.rbac.decorators import field_access_control
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.settings.utils import get_list

# Relocated to the Django-free posthog.week_start_day module so the HogQL engine can use it
# without booting Django; re-exported here for existing callers.
from posthog.week_start_day import WeekStartDay  # noqa: F401

from ...hogql.modifiers import set_default_modifier_values
from ...schema_enums import CurrencyCode, PersonsOnEventsMode
from .extensions import TeamExtensionDescriptor
from .team_caching import get_team_in_cache, set_team_in_cache

if TYPE_CHECKING:
    from posthog.schema import PathCleaningFilter

    from posthog.hogql.database.database import Database

    from posthog.models.user import User

    from products.dashboards.backend.models.dashboard import Dashboard

TIMEZONES = [(tz, tz) for tz in pytz.all_timezones]

# TODO: DEPRECATED; delete when these attributes can be fully removed from `Team` model
DEPRECATED_ATTRS = (
    "plugins_opt_in",
    "opt_out_capture",
    "event_names",
    "event_names_with_usage",
    "event_properties",
    "event_properties_with_usage",
    "event_properties_numerical",
    # Replaced by the `revenue_analytics_config` extension; only the raw-SQL Postgres->ClickHouse
    # ETL still reads the column, and that bypasses this manager.
    "revenue_tracking_config",
)

# Django requires a list of tuples for choices
CURRENCY_CODE_CHOICES = [(code.value, code.value) for code in CurrencyCode]

# Intentionally asserting this here to guarantee we remember
# to rerun migrations when a new currency is added
# python manage.py makemigrations
assert len(CURRENCY_CODE_CHOICES) == 152

DEFAULT_CURRENCY = CurrencyCode.USD.value

ASYNC_DEFAULT_STARRED_PRODUCTS_THRESHOLD = 100


class AvailableExtraSettings:
    pass


class TeamManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().defer(*DEPRECATED_ATTRS)

    def create_with_data(self, *, initiating_user: Optional["User"], **kwargs) -> "Team":
        team = cast("Team", self.create(**kwargs))

        # Create internal/test users cohort and set test_account_filters to exclude it
        from products.cohorts.backend.models.cohort import get_or_create_internal_test_users_cohort

        initiating_user_email = initiating_user.email if initiating_user else None
        test_users_cohort = get_or_create_internal_test_users_cohort(team, initiating_user_email=initiating_user_email)
        team.test_account_filters = [
            {"key": "id", "type": "cohort", "value": test_users_cohort.pk, "operator": "not_in"}
        ]

        if kwargs.get("is_demo"):
            if initiating_user is None:
                raise ValueError("initiating_user must be provided when creating a demo team")
            team.save()
            # Defer Celery task if we're inside an atomic block (e.g., ensure_account_and_save)
            # to avoid sending task before transaction commits. In tests, Celery tasks run
            # synchronously so we can call directly (and on_commit doesn't run in TestCase).
            if connection.in_atomic_block and not settings.TEST:
                transaction.on_commit(lambda: team.kick_off_demo_data_generation(initiating_user))
            else:
                team.kick_off_demo_data_generation(initiating_user)
            return team  # Return quickly, as the demo data and setup will be created asynchronously

        # Get organization to apply defaults
        organization = kwargs.get("organization") or Organization.objects.get(id=kwargs.get("organization_id"))

        team.anonymize_ips = kwargs.get("anonymize_ips", organization.default_anonymize_ips)

        # Self-hosted deployments get 5-year session recording retention by default
        if not is_cloud():
            team.session_recording_retention_period = kwargs.get(
                "session_recording_retention_period",
                SessionRecordingRetentionPeriod.FIVE_YEARS,
            )

        if team.extra_settings is None:
            team.extra_settings = {}
        team.extra_settings.setdefault("recorder_script", "posthog-recorder")

        # Create default dashboards (demo projects skip above)
        from posthog.helpers.dashboard_templates import create_from_template  # noqa: PLC0415 — breaks team import cycle

        from products.dashboards.backend.models.dashboard import Dashboard  # noqa: PLC0415 — breaks team import cycle
        from products.dashboards.backend.models.dashboard_templates import (  # noqa: PLC0415 — breaks team import cycle
            DashboardTemplate,
        )

        template = DashboardTemplate.default_signup_template()
        dashboard = Dashboard.objects.db_manager(self.db).create(
            name="Your starter dashboard",
            pinned=True,
            team=team,
            description=template.dashboard_description or "",
        )
        create_from_template(dashboard, template)
        team.primary_dashboard = dashboard

        # Create default session recording playlists
        for playlist in DEFAULT_PLAYLISTS:
            SessionRecordingPlaylist.objects.create(
                team=team,
                name=str(playlist["name"]),
                filters=playlist["filters"],
                description=str(playlist.get("description", "")),
                type="filters",
            )
        team.save()

        # Star the default products for all users who have access to this new team
        # For large orgs, dispatch async to avoid request timeouts
        from posthog.tasks.tasks import star_default_products_for_new_team

        user_count = OrganizationMembership.objects.filter(organization_id=team.organization_id).count()
        if user_count > ASYNC_DEFAULT_STARRED_PRODUCTS_THRESHOLD:
            transaction.on_commit(lambda: star_default_products_for_new_team.delay(team.id))
        else:
            star_default_products_for_new_team(team.id)

        return team

    def create(self, **kwargs):
        from ..project import Project

        with transaction.atomic(using=self.db):
            if "id" not in kwargs:
                kwargs["id"] = self.increment_id_sequence()
            if kwargs.get("project") is None and kwargs.get("project_id") is None:
                # If a parent project is not provided for this team, ensure there is one
                # This should be removed once environments are fully rolled out
                project_kwargs = {}
                if organization := kwargs.get("organization"):
                    project_kwargs["organization"] = organization
                elif organization_id := kwargs.get("organization_id"):
                    project_kwargs["organization_id"] = organization_id
                if name := kwargs.get("name"):
                    project_kwargs["name"] = name
                kwargs["project"] = Project.objects.db_manager(self.db).create(id=kwargs["id"], **project_kwargs)
            return super().create(**kwargs)

    def get_team_from_token(self, token: Optional[str]) -> Optional["Team"]:
        if not token:
            return None
        try:
            return Team.objects.get(api_token=token)
        except Team.DoesNotExist:
            return None

    def get_team_from_cache_or_token(self, token: Optional[str]) -> Optional["Team"]:
        if not token:
            return None
        try:
            team = get_team_in_cache(token)
            if team:
                return team

            team = Team.objects.get(api_token=token)
            set_team_in_cache(token, team)
            return team

        except Team.DoesNotExist:
            return None

    def get_team_from_cache_or_secret_api_token(self, secret_api_token: Optional[str]) -> Optional["Team"]:
        if not secret_api_token:
            return None
        try:
            team = get_team_in_cache(secret_api_token)
            if team:
                return team

            team = Team.objects.get(secret_api_token=secret_api_token)
            set_team_in_cache(secret_api_token, team)
            return team

        except Team.DoesNotExist:
            return None

    def increment_id_sequence(self) -> int:
        """Increment the `Team.id` field's sequence and return the latest value.

        Use only when actually neeeded to avoid wasting sequence values."""
        cursor = connection.cursor()
        cursor.execute("SELECT nextval('posthog_team_id_seq')")
        result = cursor.fetchone()
        return result[0]


def get_default_data_attributes() -> list[str]:
    return ["data-attr"]


class CookielessServerHashMode(models.IntegerChoices):
    DISABLED = 0, "Disabled"
    STATELESS = 1, "Stateless"
    STATEFUL = 2, "Stateful"


class BusinessModel(models.TextChoices):
    B2B = "b2b", "B2B"
    B2C = "b2c", "B2C"
    OTHER = "other", "Other"


class SessionRecordingRetentionPeriod(models.TextChoices):
    THIRTY_DAYS = "30d", "30 Days"
    NINETY_DAYS = "90d", "90 Days"
    ONE_YEAR = "1y", "1 Year"
    FIVE_YEARS = "5y", "5 Years"


class Team(UUIDTClassicModel):
    """Team means "environment" (historically it meant "project", but now we have the parent Project model for that)."""

    class Meta:
        verbose_name = "environment (aka team)"
        verbose_name_plural = "environments (aka teams)"
        # Route forward-FK / related-object loads (e.g. `request.user.current_team`) through the
        # `objects` manager so they inherit its `.defer(*DEPRECATED_ATTRS)`. Without this, Django
        # falls back to a bare `Manager()` for related access and re-loads the fat deprecated
        # taxonomy columns on every such fetch — on the hot path that's every authenticated request.
        base_manager_name = "objects"
        indexes = [
            HashIndex(
                KeyTransform("widget_public_token", "conversations_settings"),
                condition=models.Q(conversations_enabled=True),
                name="posthog_team_widget_token_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                name="project_id_is_not_null",
                # We have this as a constraint rather than IS NOT NULL on the field, because setting IS NOT NULL cannot
                # be done without locking the table. By adding this constraint using Postgres's `NOT VALID` option
                # (via Django `AddConstraintNotValid()`) and subsequent `VALIDATE CONSTRAINT`, we avoid locking.
                condition=models.Q(project_id__isnull=False),
            ),
            models.CheckConstraint(
                name="llm_gateway_overspend_allowance_usd_in_range",
                # Mirrors OVERSPEND_ALLOWANCE_MIN/MAX_USD; null = unset stays valid. The Python
                # write surfaces validate too, but update/bulk_update/shell/raw bypass them.
                condition=models.Q(llm_gateway_overspend_allowance_usd__isnull=True)
                | models.Q(
                    llm_gateway_overspend_allowance_usd__gte=0,
                    llm_gateway_overspend_allowance_usd__lte=10000,
                ),
            ),
        ]

    objects: TeamManager = TeamManager()

    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="teams",
        related_query_name="team",
    )
    # NOTE: The deletion is not cascade due to us wanting to first of all solve deletion properly before allowing cascading deletes
    parent_team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.SET_NULL,
        related_name="child_teams",
        related_query_name="child_team",
        null=True,
    )
    # NOTE: To be removed in favour of parent_team
    project = models.ForeignKey(
        "posthog.Project",
        on_delete=models.CASCADE,
        related_name="teams",
        related_query_name="team",
    )
    api_token = models.CharField(
        max_length=200,
        unique=True,
        default=generate_random_token_project,
        validators=[MinLengthValidator(10, "Project's API token must be at least 10 characters long!")],
    )
    app_urls: ArrayField = field_access_control(
        ArrayField(models.CharField(max_length=200, null=True), default=list, blank=True), "web_analytics", "editor"
    )
    name = models.CharField(
        max_length=200,
        default="Default project",
        validators=[MinLengthValidator(1, "Project must have a name!")],
    )
    # DEPRECATED - not used anywhere and eligible for deletion
    slack_incoming_webhook = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    anonymize_ips = field_access_control(models.BooleanField(default=False), "project", "admin")
    completed_snippet_onboarding = models.BooleanField(default=False)
    has_completed_onboarding_for = models.JSONField(null=True, blank=True)
    onboarding_tasks = models.JSONField(null=True, blank=True)
    ingested_event = models.BooleanField(default=False)
    ingested_production_event = models.BooleanField(default=False, db_default=False)
    ingested_production_event_last_checked_at = models.DateTimeField(null=True, blank=True)

    person_processing_opt_out = field_access_control(models.BooleanField(null=True, default=False), "project", "admin")
    secret_api_token = models.CharField(
        max_length=200,
        null=True,
        blank=True,
    )
    secret_api_token_backup = models.CharField(
        max_length=200,
        null=True,
        blank=True,
    )

    # Session recording
    session_recording_opt_in = field_access_control(models.BooleanField(default=False), "project", "admin")
    session_recording_sample_rate = field_access_control(
        models.DecimalField(
            # will store a decimal between 0 and 1 allowing up to 2 decimal places
            null=True,
            blank=True,
            max_digits=3,
            decimal_places=2,
            validators=[MinValueValidator(Decimal(0)), MaxValueValidator(Decimal(1))],
        ),
        "project",
        "admin",
    )
    session_recording_minimum_duration_milliseconds = field_access_control(
        models.IntegerField(
            null=True,
            blank=True,
            validators=[MinValueValidator(0), MaxValueValidator(30000)],
        ),
        "project",
        "admin",
    )
    session_recording_linked_flag = field_access_control(models.JSONField(null=True, blank=True), "project", "admin")
    session_recording_network_payload_capture_config = field_access_control(
        models.JSONField(null=True, blank=True), "project", "admin"
    )
    session_recording_masking_config = field_access_control(models.JSONField(null=True, blank=True), "project", "admin")
    session_recording_url_trigger_config = field_access_control(
        ArrayField(models.JSONField(null=True, blank=True), default=list, blank=True, null=True),
        "project",
        "admin",
    )
    session_recording_url_blocklist_config = field_access_control(
        ArrayField(models.JSONField(null=True, blank=True), default=list, blank=True, null=True),
        "project",
        "admin",
    )
    session_recording_event_trigger_config = field_access_control(
        ArrayField(models.TextField(null=True, blank=True), default=list, blank=True, null=True),
        "project",
        "admin",
    )
    session_recording_trigger_match_type_config = field_access_control(
        models.CharField(null=True, blank=True, max_length=24),
        "project",
        "admin",
    )
    session_recording_trigger_groups = field_access_control(
        models.JSONField(
            null=True,
            blank=True,
            help_text="V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.",
        ),
        "project",
        "admin",
    )
    session_replay_config = field_access_control(models.JSONField(null=True, blank=True), "project", "admin")
    session_recording_retention_period = field_access_control(
        models.CharField(
            max_length=3,
            choices=SessionRecordingRetentionPeriod,
            default=SessionRecordingRetentionPeriod.THIRTY_DAYS,
        ),
        "project",
        "admin",
    )

    # Events data retention in months — denormalized from the billing entitlement by sync_events_retention, read on
    # the HogQL hot path. Default 84 (7 years) grandfathers existing teams. db_default because posthog_team is also
    # written by raw inserts in nodejs/rust and the test-schema builder.
    event_retention_months = field_access_control(
        models.PositiveSmallIntegerField(default=84, db_default=84),
        "project",
        "admin",
    )

    # Conversations
    conversations_enabled = field_access_control(models.BooleanField(null=True, blank=True), "project", "admin")
    conversations_settings = field_access_control(models.JSONField(null=True, blank=True), "project", "admin")

    # Proactive tasks (#team-self-driving)
    proactive_tasks_enabled = models.BooleanField(null=True, blank=True)

    # Surveys
    survey_config = field_access_control(models.JSONField(null=True, blank=True), "project", "admin")
    surveys_opt_in = field_access_control(models.BooleanField(null=True, blank=True), "project", "admin")

    # Product tours
    product_tours_opt_in = field_access_control(models.BooleanField(null=True, blank=True), "project", "admin")

    # Capture / Autocapture
    capture_console_log_opt_in = field_access_control(
        models.BooleanField(null=True, blank=True, default=True), "project", "admin"
    )
    capture_performance_opt_in = field_access_control(
        models.BooleanField(null=True, blank=True, default=True), "project", "admin"
    )
    capture_dead_clicks = field_access_control(
        models.BooleanField(null=True, blank=True, default=False), "project", "admin"
    )
    autocapture_opt_out = field_access_control(models.BooleanField(null=True, blank=True), "project", "admin")
    autocapture_web_vitals_opt_in = field_access_control(models.BooleanField(null=True, blank=True), "project", "admin")
    autocapture_web_vitals_allowed_metrics = field_access_control(
        models.JSONField(null=True, blank=True), "project", "admin"
    )
    autocapture_exceptions_opt_in = field_access_control(models.BooleanField(null=True, blank=True), "project", "admin")
    autocapture_exceptions_errors_to_ignore = field_access_control(
        models.JSONField(null=True, blank=True), "project", "admin"
    )

    # Logs
    logs_settings = field_access_control(models.JSONField(null=True, blank=True), "project", "admin")

    # LLM gateway — per-team admission projection read by the llm-gateway Go
    # service via a purpose-built HyperCache blob (cache/team_tokens/<token>/
    # team_metadata/llm_gateway_policy.json). The gateway admits a team only
    # when llm_gateway_enabled_at is set and llm_gateway_revoked_at is null;
    # revoke wins over enable. Null enabled_at = not enrolled (default-deny);
    # null revoked_at = not revoked. Set by internal tooling/admin only.
    llm_gateway_enabled_at = models.DateTimeField(null=True, blank=True)
    llm_gateway_revoked_at = models.DateTimeField(null=True, blank=True)
    # Per-team USD floor the gateway lets a team dispatch past $0 down to. Projected into
    # gateway_credential.json as the `overspend_allowance_usd` wire key. Null = use the
    # gateway default; 0 = no allowance. Range [0, 10000] validated at the write surfaces.
    llm_gateway_overspend_allowance_usd = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)

    # Heatmaps
    heatmaps_opt_in = field_access_control(models.BooleanField(null=True, blank=True), "project", "admin")

    # Activity logs
    receive_org_level_activity_logs = field_access_control(
        models.BooleanField(null=True, blank=True, default=False), "project", "admin"
    )

    # Web analytics
    web_analytics_pre_aggregated_tables_enabled = field_access_control(
        models.BooleanField(default=False, null=True), "project", "admin"
    )
    web_analytics_pre_aggregated_tables_version = field_access_control(
        models.CharField(max_length=10, default="v2", null=True, choices=[("v1", "v1"), ("v2", "v2")]),
        "project",
        "admin",
    )

    # Feature flags
    flags_persistence_default = field_access_control(
        models.BooleanField(null=True, blank=True, default=False), "project", "admin"
    )
    feature_flag_confirmation_enabled = field_access_control(
        models.BooleanField(null=True, blank=True, default=False), "project", "admin"
    )
    feature_flag_confirmation_message = field_access_control(
        models.TextField(null=True, blank=True), "project", "admin"
    )
    # DEPRECATED: Use default_evaluation_contexts_enabled instead. Will be removed in a future migration after full rollout.
    default_evaluation_environments_enabled = models.BooleanField(null=True, blank=True, default=False)
    # DEPRECATED: Use require_evaluation_contexts instead. Will be removed in a future migration after full rollout.
    require_evaluation_environment_tags = models.BooleanField(null=True, blank=True, default=False)
    default_evaluation_contexts_enabled = field_access_control(
        models.BooleanField(
            null=True,
            blank=True,
            default=False,
            help_text="Whether to automatically apply default evaluation contexts to new feature flags",
        ),
        "project",
        "admin",
    )
    require_evaluation_contexts = field_access_control(
        models.BooleanField(
            null=True,
            blank=True,
            default=False,
            help_text="Whether to require at least one evaluation context tag when creating new feature flags",
        ),
        "project",
        "admin",
    )
    session_recording_version = field_access_control(
        models.CharField(null=True, blank=True, max_length=24), "project", "admin"
    )
    signup_token = models.CharField(max_length=200, null=True, blank=True)
    is_demo = field_access_control(models.BooleanField(default=False), "project", "admin")

    # DEPRECATED - do not use
    access_control = models.BooleanField(default=False)

    week_start_day = field_access_control(
        models.SmallIntegerField(null=True, blank=True, choices=WeekStartDay), "project", "admin"
    )
    # This is not a manual setting. It's updated automatically to reflect if the team uses site apps or not.
    inject_web_apps = models.BooleanField(null=True)

    test_account_filters = field_access_control(
        models.JSONField(
            default=list,
            help_text="""Filters used to identify internal/test users. Each entry is a property filter.

            Supported entry types and the exact shape each accepts:

            # Person property — match (or exclude) by a person property
            {"key": "email", "type": "person", "value": "@example.com", "operator": "ends_with"}

            # Event property — match by an event property
            {"key": "$host", "type": "event", "value": "localhost", "operator": "icontains"}

            # Cohort membership — match (or exclude) members of a cohort.
            # Use operator "in" for inclusion and "not_in" for exclusion. Do NOT use a
            # `negation` field here — `negation` is specific to cohort *definitions*
            # (the inner sub-filters that build a cohort) and is rejected by the
            # property-filter schema.
            {"key": "id", "type": "cohort", "value": 8814, "operator": "not_in"}

            Common operators: "exact", "is_not", "icontains", "not_icontains", "starts_with",
            "not_starts_with", "ends_with", "not_ends_with", "regex", "not_regex", "gt", "lt",
            "gte", "lte", "is_set", "is_not_set", "in", "not_in".""",
        ),
        "project",
        "admin",
    )
    test_account_filters_default_checked = field_access_control(
        models.BooleanField(null=True, blank=True), "project", "admin"
    )

    path_cleaning_filters = field_access_control(
        models.JSONField(default=list, null=True, blank=True), "project", "admin"
    )

    timezone = field_access_control(
        models.CharField(max_length=240, choices=TIMEZONES, default="UTC"), "project", "admin"
    )
    data_attributes = field_access_control(
        models.JSONField(default=get_default_data_attributes, blank=True), "project", "admin"
    )
    person_display_name_properties: ArrayField = field_access_control(
        ArrayField(models.CharField(max_length=400), null=True, blank=True), "project", "admin"
    )
    live_events_columns: ArrayField = field_access_control(
        ArrayField(models.TextField(), null=True, blank=True), "project", "admin"
    )
    recording_domains: ArrayField = field_access_control(
        ArrayField(models.CharField(max_length=200, null=True), blank=True, null=True), "project", "admin"
    )
    human_friendly_comparison_periods = field_access_control(
        models.BooleanField(default=False, null=True, blank=True), "project", "admin"
    )
    # Enable/disable toggle for cookieless ingestion. STATELESS (1) is sunset: any non-disabled
    # value is processed as stateful.
    cookieless_server_hash_mode = field_access_control(
        models.SmallIntegerField(
            default=CookielessServerHashMode.DISABLED,
            choices=CookielessServerHashMode,
            null=True,
        ),
        "project",
        "admin",
    )

    primary_dashboard = models.ForeignKey(
        "dashboards.Dashboard",
        on_delete=models.SET_NULL,
        null=True,
        related_name="primary_dashboard_teams",
        blank=True,
    )  # Dashboard shown on project homepage

    # Exposed as a field on TeamSerializer/ProjectSerializer, so this descriptor is required per
    # posthog/models/team/README.md ("An extension exposed as a nested field on the team or
    # project serializer is the exception, and does need the descriptor.").
    @property
    def home_tab_dashboard(self) -> "Dashboard | None":
        from products.dashboards.backend.models import TeamHomeTabDashboardConfig

        config = TeamHomeTabDashboardConfig.objects.for_team(self.pk).select_related("dashboard").first()
        dashboard = config.dashboard if config else None
        return dashboard if dashboard and not dashboard.deleted and dashboard.team_id == self.pk else None

    @home_tab_dashboard.setter
    def home_tab_dashboard(self, dashboard: "Dashboard | None") -> None:
        from products.dashboards.backend.models import TeamHomeTabDashboardConfig

        config, _ = TeamHomeTabDashboardConfig.objects.for_team(self.pk).get_or_create(team_id=self.pk)
        config.dashboard = dashboard
        config.save(update_fields=["dashboard"])

    default_data_theme = field_access_control(models.IntegerField(null=True, blank=True), "project", "admin")

    # Generic field for storing any team-specific context
    # that likely doesn't deserve a dedicated column. Can be used for things like settings and overrides
    # during feature releases.
    extra_settings = models.JSONField(null=True, blank=True)

    # Environment-level default HogQL query modifiers
    modifiers = field_access_control(models.JSONField(null=True, blank=True), "project", "admin")

    # This is meant to be used as a stopgap until https://github.com/PostHog/meta/pull/39 gets implemented
    # Switches _most_ queries to using distinct_id as aggregator instead of person_id
    @property
    def aggregate_users_by_distinct_id(self) -> bool:
        return str(self.pk) in get_list(get_instance_setting("AGGREGATE_BY_DISTINCT_IDS_TEAMS"))

    correlation_config = deprecate_field(models.JSONField(default=dict, null=True, blank=True))

    # DEPRECATED, DISUSED: recordings on CH are cleared with Clickhouse's TTL
    session_recording_retention_period_days = models.IntegerField(null=True, default=None, blank=True)
    # DEPRECATED, DISUSED: plugins are enabled for everyone now
    plugins_opt_in = models.BooleanField(default=False)
    # DEPRECATED, DISUSED: replaced with env variable OPT_OUT_CAPTURE and User.anonymized_data
    opt_out_capture = models.BooleanField(default=False)
    # DEPRECATED: in favor of `EventDefinition` model
    event_names = models.JSONField(default=list, blank=True)
    event_names_with_usage = models.JSONField(default=list, blank=True)
    # DEPRECATED: in favor of `PropertyDefinition` model
    event_properties = models.JSONField(default=list, blank=True)
    event_properties_with_usage = models.JSONField(default=list, blank=True)
    event_properties_numerical = models.JSONField(default=list, blank=True)
    external_data_workspace_id = models.CharField(max_length=400, null=True, blank=True)
    external_data_workspace_last_synced_at = models.DateTimeField(null=True, blank=True)

    api_query_rate_limit = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        help_text="Custom rate limit for HogQL API queries in #requests/{sec,min,hour,day}",
        validators=[validate_rate_limit],
    )

    # DEPRECATED: use `revenue_analytics_config` property instead
    revenue_tracking_config = models.JSONField(null=True, blank=True)

    # Duration for dropping events older than this threshold
    drop_events_older_than = models.DurationField(
        null=True,
        blank=True,
        validators=[MinValueValidator(timedelta(hours=1))],  # For safety minimum 1h
        help_text="Events older than this threshold will be dropped in ingestion. Empty means no timestamp restrictions.",
    )

    # Consolidated base currency for all analytics (revenue, marketing, etc.)
    base_currency = field_access_control(
        models.CharField(
            max_length=3,
            choices=CURRENCY_CODE_CHOICES,
            default=DEFAULT_CURRENCY,
            null=True,
            blank=True,
        ),
        "project",
        "admin",
    )

    business_model = field_access_control(
        models.CharField(
            max_length=10,
            choices=BusinessModel,
            null=True,
            blank=True,
            help_text="Whether this project serves B2B or B2C customers, used to optimize the UI layout.",
        ),
        "project",
        "admin",
    )

    # Before adding new fields here, read posthog/models/team/README.md
    # Domain-specific config should use a Team Extension model instead.

    # TRANSITIONAL: These accessors exist for backward compat with existing
    # `team.<product>_config` call sites. New products should NOT add accessors
    # here — use get_or_create_team_extension() at call sites instead.
    #
    # One exception, and the reason every config below is also a team/project serializer field: a
    # config exposed that way needs the attribute. DRF skips a required=False field whose attribute
    # is missing, so dropping one of these accessors strips the setting from every API response
    # without raising. A config no serializer exposes needs no accessor here, and is reached through
    # the helper the way TeamFeatureFlagDefaultsConfig is.

    revenue_analytics_config = TeamExtensionDescriptor(
        "posthog.models.team.team_revenue_analytics_config", "TeamRevenueAnalyticsConfig"
    )
    marketing_analytics_config = TeamExtensionDescriptor(
        "posthog.models.team.team_marketing_analytics_config", "TeamMarketingAnalyticsConfig"
    )
    customer_analytics_config = TeamExtensionDescriptor(
        "products.customer_analytics.backend.facade.team_extension", "TeamCustomerAnalyticsConfig"
    )
    workflows_config = TeamExtensionDescriptor(
        "products.workflows.backend.facade.team_extension", "TeamWorkflowsConfig"
    )
    feature_flag_policy_config = TeamExtensionDescriptor(
        "products.feature_flags.backend.models.team_feature_flag_policy_config", "TeamFeatureFlagPolicyConfig"
    )

    @property
    def default_modifiers(self) -> dict:
        # Deferred: posthog.schema (the pydantic models) stays off django.setup(),
        # where this model loads in every process.
        from posthog.schema import HogQLQueryModifiers  # noqa: PLC0415

        modifiers = HogQLQueryModifiers()
        set_default_modifier_values(modifiers, self)
        return modifiers.model_dump()

    @property
    def person_on_events_mode(self) -> PersonsOnEventsMode:
        if self.modifiers and self.modifiers.get("personsOnEventsMode") is not None:
            # HogQL modifiers (which also act as the project-level setting) take precedence
            mode = PersonsOnEventsMode(self.modifiers["personsOnEventsMode"])
        else:
            # Otherwise use the flag-based default
            mode = self.person_on_events_mode_flag_based_default
        tag_queries(person_on_events_mode=mode)
        return mode

    @property
    def person_on_events_mode_flag_based_default(self) -> PersonsOnEventsMode:
        if self._person_on_events_person_id_override_properties_on_events:
            return PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS

        if self._person_on_events_person_id_no_override_properties_on_events:
            return PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS

        return PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED

    # KLUDGE: DO NOT REFERENCE IN THE BACKEND!
    # Keeping this property for now only to be used by the frontend in certain cases
    @property
    def person_on_events_querying_enabled(self) -> bool:
        return self.person_on_events_mode in (  # Whether person properties on events are in use by default
            PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
            PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
        )

    @property
    def _person_on_events_person_id_no_override_properties_on_events(self) -> bool:
        person_on_events_override = getattr(settings, "PERSON_ON_EVENTS_OVERRIDE", None)
        if person_on_events_override is not None:
            return person_on_events_override

        # on PostHog Cloud, use the feature flag
        if is_cloud():
            return feature_enabled_or_false(
                "persons-on-events-person-id-no-override-properties-on-events",
                str(self.uuid),
                groups={"project": str(self.id)},
                group_properties={
                    "project": {
                        "id": str(self.id),
                        "created_at": self.created_at.isoformat() if self.created_at else None,
                        "uuid": self.uuid,
                    }
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )

        # on self-hosted, use the instance setting
        return get_instance_setting("PERSON_ON_EVENTS_ENABLED")

    @property
    def _person_on_events_person_id_override_properties_on_events(self) -> bool:
        person_on_events_v2_override = getattr(settings, "PERSON_ON_EVENTS_V2_OVERRIDE", None)
        if person_on_events_v2_override is not None:
            return person_on_events_v2_override

        # on PostHog Cloud, use the feature flag
        if is_cloud():
            return feature_enabled_or_false(
                "persons-on-events-v2-reads-enabled",
                str(self.uuid),
                groups={"organization": str(self.organization_id)},
                group_properties={
                    "organization": {
                        "id": str(self.organization_id),
                        "created_at": self.organization.created_at.isoformat()
                        if self.organization.created_at
                        else None,
                    }
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )

        return get_instance_setting("PERSON_ON_EVENTS_V2_ENABLED")

    @property
    def strict_caching_enabled(self) -> bool:
        enabled_teams = get_list(get_instance_setting("STRICT_CACHING_TEAMS"))
        return str(self.pk) in enabled_teams or "all" in enabled_teams

    def count_persons_seen_so_far(self, database: Optional["Database"] = None) -> int:
        from posthog.schema import HogQLQueryModifiers

        from posthog.hogql.context import HogQLContext
        from posthog.hogql.query import execute_hogql_query

        from posthog.schema_enums import PersonsArgMaxVersion

        with tags_context(product=Product.FEATURE_FLAGS, feature=Feature.QUERY):
            return execute_hogql_query(
                "SELECT count() FROM persons",
                team=self,
                query_type="persons_seen_so_far",
                # Pin v1 because the v2 persons path pushes the executor's default LIMIT into its
                # dedup subquery, which caps a bare count() at ~101 for teams pinned to v2 (see #87323).
                modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.V1),
                # A caller that runs several queries can pass a prebuilt database to skip a rebuild.
                # The v1 pin survives a shared database: the persons table reads the dedup mode from
                # each query's modifiers at print time, not from the database.
                context=HogQLContext(team_id=self.pk, database=database),
            ).results[0][0]

    def count_groups_seen_so_far(self, group_type_index: GroupTypeIndex, database: Optional["Database"] = None) -> int:
        from posthog.hogql import ast  # noqa: PLC0415 — breaks team import cycle
        from posthog.hogql.context import HogQLContext  # noqa: PLC0415 — breaks team import cycle
        from posthog.hogql.query import execute_hogql_query  # noqa: PLC0415 — breaks team import cycle

        with tags_context(product=Product.FEATURE_FLAGS, feature=Feature.QUERY):
            return execute_hogql_query(
                # `raw_groups` holds one row per group update, so DISTINCT does the dedup. The `groups`
                # lazy table would first collapse every row of the team through its argMax subquery.
                "SELECT count(DISTINCT key) FROM raw_groups WHERE index = {group_type_index}",
                placeholders={"group_type_index": ast.Constant(value=group_type_index)},
                team=self,
                query_type="groups_seen_so_far",
                # A caller that runs several queries can pass a prebuilt database to skip a rebuild.
                context=HogQLContext(team_id=self.pk, database=database),
            ).results[0][0]

    @property
    def timezone_info(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def path_cleaning_filter_models(self) -> list["PathCleaningFilter"]:
        from posthog.schema import PathCleaningFilter  # noqa: PLC0415

        filters = []
        for f in self.path_cleaning_filters:
            try:
                filters.append(PathCleaningFilter.model_validate(f))
            except pydantic.ValidationError:
                continue
        return filters

    def reset_token_and_save(self, *, user: "User", is_impersonated_session: bool):
        old_token = self.api_token
        self.api_token = generate_random_token_project()
        self._persist_api_token_change(old_token=old_token, user=user, is_impersonated_session=is_impersonated_session)

    def _notify_vercel_of_token_rotation(self) -> None:
        """Push updated API token to Vercel integrations in the background."""
        from posthog.tasks.integrations import push_vercel_secrets

        push_vercel_secrets.delay(self.id)

    def set_token_and_save(self, *, new_token: str, user: "User", is_impersonated_session: bool):
        new_token = new_token.strip()
        if not new_token:
            raise ValueError("New API token must be non-empty.")
        api_token_field = self._meta.get_field("api_token")
        if not isinstance(api_token_field, models.CharField) or api_token_field.max_length is None:
            raise RuntimeError("Team.api_token field must declare a max_length")
        api_token_max_length = api_token_field.max_length
        if len(new_token) > api_token_max_length:
            raise ValueError(f"New API token exceeds {api_token_max_length} characters.")
        if new_token == self.api_token:
            raise ValueError("New API token is identical to the current token.")
        if Team.objects.filter(api_token=new_token).exclude(pk=self.pk).exists():
            raise ValueError("New API token is already in use by another team.")

        old_token = self.api_token
        self.api_token = new_token
        self._persist_api_token_change(old_token=old_token, user=user, is_impersonated_session=is_impersonated_session)

    def _persist_api_token_change(self, *, old_token: str, user: "User", is_impersonated_session: bool) -> None:
        from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
        from posthog.tasks.remote_config import update_team_remote_config

        self.save()
        # The post_save receiver also dispatches the plain remote config sync for this save.
        # A worker that predates the old_token argument rejects this task. That worker still
        # runs the plain sync, which writes the new token's Redis entry.
        transaction.on_commit(lambda: update_team_remote_config.delay(self.id, old_token=old_token))
        set_team_in_cache(old_token, None)
        set_team_in_cache(self.api_token, self)
        log_activity(
            organization_id=self.organization_id,
            team_id=self.pk,
            user=cast("User", user),
            was_impersonated=is_impersonated_session,
            scope="Team",
            item_id=self.pk,
            activity="updated",
            detail=Detail(
                name=str(self.name),
                changes=[
                    Change(
                        type="Team",
                        action="changed",
                        field="api_token",
                        before=old_token,
                        after=self.api_token,
                    )
                ],
            ),
        )

        self._notify_vercel_of_token_rotation()

    def rotate_secret_token_and_save(self, *, user: "User", is_impersonated_session: bool):
        from posthog.models.activity_logging.activity_log import Change, Detail, log_activity

        new_token = generate_random_token_secret()
        # One transaction with the signal receivers: the conversations signing secret must
        # never diverge from the column, so a failed copy rolls the rotation back whole.
        try:
            with transaction.atomic():
                # A rotation racing this one would overwrite the token this save writes while
                # its mirror row lives on as a working credential, so read under lock.
                locked = Team.objects.select_for_update(no_key=True).get(pk=self.pk)
                old_primary_token = locked.secret_api_token
                expired_token = locked.secret_api_token_backup
                self.secret_api_token = new_token
                self.secret_api_token_backup = old_primary_token
                self.save()
                if expired_token:
                    # Retire the expiring token's mirror row with it, or it keeps authenticating.
                    delete_project_secret_api_keys_for_token(self.id, expired_token)
                # With the legacy verifiers off, only the mirror row authenticates the new token.
                create_project_secret_api_key_for_token(self.id, new_token)
                secret_api_token_rotated.send(sender=self.__class__, team=self)
        except Exception:
            # save() already cached this team (post_save) with the new tokens, which the
            # rollback discarded. Rewrite that entry from the committed row.
            self.refresh_from_db(fields=["secret_api_token", "secret_api_token_backup"])
            set_team_in_cache(self.api_token, self)
            raise

        set_team_in_cache(new_token, self)
        # Old token needs to continue to work until it's deleted.
        if old_primary_token:
            set_team_in_cache(old_primary_token, self)
        if expired_token:
            # Clear the previous backup token from cache since it's being replaced
            set_team_in_cache(expired_token, None)

        # Build up the changes.

        masked_old_primary_token = mask_key_value(old_primary_token) if old_primary_token else None

        before = {
            "secret_api_token": masked_old_primary_token,
        }
        after = {
            "secret_api_token": mask_key_value(new_token),
        }

        if masked_old_primary_token:
            # We rotated keys rather than generated a new one.
            before["secret_api_token_backup"] = mask_key_value(expired_token) if expired_token else None
            after["secret_api_token_backup"] = masked_old_primary_token

        log_activity(
            organization_id=self.organization_id,
            team_id=self.pk,
            user=cast("User", user),
            was_impersonated=is_impersonated_session,
            scope="Team",
            item_id=self.pk,
            activity="updated",
            detail=Detail(
                name=str(self.name),
                changes=[
                    Change(
                        type="Team",
                        action="created" if old_primary_token is None else "changed",
                        field="secret_api_token",
                        before=before,
                        after=after,
                    )
                ],
            ),
        )

    def generate_conversations_public_token_and_save(self, *, user: "User", is_impersonated_session: bool):
        """Generate or regenerate the conversations public token for widget authentication."""
        from posthog.models.activity_logging.activity_log import Change, Detail, log_activity

        settings = self.conversations_settings or {}
        old_token = settings.get("widget_public_token")
        new_token = generate_random_token_project()
        settings["widget_public_token"] = new_token
        self.conversations_settings = settings
        self.save()

        log_activity(
            organization_id=self.organization_id,
            team_id=self.pk,
            user=cast("User", user),
            was_impersonated=is_impersonated_session,
            scope="Team",
            item_id=self.pk,
            activity="updated",
            detail=Detail(
                name=str(self.name),
                changes=[
                    Change(
                        type="Team",
                        action="created" if old_token is None else "changed",
                        field="conversations_settings.widget_public_token",
                        before=mask_key_value(old_token) if old_token else None,
                        after=mask_key_value(new_token),
                    )
                ],
            ),
        )

    @property
    def heatmaps_screenshot_secret(self) -> str | None:
        from posthog.models.team.team_heatmap_config import TeamHeatmapConfig

        config = TeamHeatmapConfig.objects.filter(team_id=self.pk).first()
        return config.screenshot_secret if config else None

    def rotate_heatmaps_screenshot_secret_and_save(self, *, user: "User", is_impersonated_session: bool) -> None:
        from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
        from posthog.models.team.extensions import get_or_create_team_extension
        from posthog.models.team.team_heatmap_config import TeamHeatmapConfig

        get_or_create_team_extension(self, TeamHeatmapConfig)
        with transaction.atomic():
            config = TeamHeatmapConfig.objects.select_for_update().get(team_id=self.pk)
            old_secret = config.screenshot_secret
            config.screenshot_secret = generate_random_token_heatmap_screenshot()
            config.save(update_fields=["screenshot_secret"])

            log_activity(
                organization_id=self.organization_id,
                team_id=self.pk,
                user=cast("User", user),
                was_impersonated=is_impersonated_session,
                scope="Team",
                item_id=self.pk,
                activity="updated",
                detail=Detail(
                    name=str(self.name),
                    changes=[
                        Change(
                            type="Team",
                            action="created" if old_secret is None else "changed",
                            field="heatmaps_screenshot_secret",
                            before="redacted" if old_secret else None,
                            after="redacted",
                        )
                    ],
                ),
            )

    def delete_secret_token_backup_and_save(self, *, user: "User", is_impersonated_session: bool):
        from posthog.models.activity_logging.activity_log import Change, Detail, log_activity

        try:
            with transaction.atomic():
                # A rotation racing this delete rewrites the backup column, so read under lock.
                # No in-memory precheck: this instance may predate a rotation that set the backup.
                locked = Team.objects.select_for_update(no_key=True).get(pk=self.pk)
                old_backup_token = locked.secret_api_token_backup
                if not old_backup_token:
                    return
                # save() writes every field, so a stale primary here would clobber a
                # concurrently rotated token while its mirror row keeps authenticating.
                self.secret_api_token = locked.secret_api_token
                self.secret_api_token_backup = None
                self.save()
                delete_project_secret_api_keys_for_token(self.id, old_backup_token)
        except Exception:
            # save() already cached this team (post_save) with the cleared backup, which
            # the rollback discarded. Rewrite that entry from the committed row.
            self.refresh_from_db(fields=["secret_api_token", "secret_api_token_backup"])
            set_team_in_cache(self.api_token, self)
            raise
        set_team_in_cache(old_backup_token, None)

        log_activity(
            organization_id=self.organization_id,
            team_id=self.pk,
            user=cast("User", user),
            was_impersonated=is_impersonated_session,
            scope="Team",
            item_id=self.pk,
            activity="updated",
            detail=Detail(
                name=str(self.name),
                changes=[
                    Change(
                        type="Team",
                        action="deleted",
                        field="secret_api_token_backup",
                        before=mask_key_value(old_backup_token),
                        after=None,
                    )
                ],
            ),
        )

    def get_is_generating_demo_data(self) -> bool:
        cache_key = f"is_generating_demo_data_{self.id}"
        return cache.get(cache_key) == "True"

    def kick_off_demo_data_generation(self, initiating_user: "User") -> None:
        from posthog.tasks.demo_create_data import create_data_for_demo_team

        cache_key = f"is_generating_demo_data_{self.id}"
        cache.set(cache_key, "True")  # Create an item in the cache that we can use to see if the demo data is ready
        create_data_for_demo_team.delay(self.id, initiating_user.id, cache_key)

    def all_users_with_access(self, *, user_uuids: Optional[Collection[str]] = None) -> QuerySet["User"]:
        from posthog.constants import AvailableFeature  # noqa: PLC0415
        from posthog.models.user import User  # noqa: PLC0415

        from products.access_control.backend.facade.subject_access_control import (  # noqa: PLC0415 - circular
            SubjectAccessControl,
        )
        from products.access_control.backend.models.access_control import AccessControl  # noqa: PLC0415
        from products.access_control.backend.models.role import RoleMembership  # noqa: PLC0415

        organization = self.organization
        member_queryset = OrganizationMembership.objects.filter(organization_id=self.organization_id)
        if user_uuids is not None:
            member_queryset = member_queryset.filter(user__uuid__in=user_uuids)
        # An organization without ACCESS_CONTROL has no private projects, so every active member
        # has access. Return a SQL subquery so `.exists()`, `.count()`, and `.filter()` callers
        # answer in Postgres instead of materializing every membership here first.
        if not organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
            member_user_ids = member_queryset.values_list("user_id", flat=True)
            return User.objects.filter(is_active=True, id__in=member_user_ids)

        team_rows = list(AccessControl.objects.filter(team_id=self.id, resource="project", resource_id=str(self.id)))
        role_based_access_supported = organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS)
        # A rule that can give one member a different answer than the next: an own-member rule,
        # or (when the entitlement is on) a role rule.
        has_discriminating_rules = any(
            row.organization_member_id is not None or (row.role_id is not None and role_based_access_supported)
            for row in team_rows
        )

        # Fast path: without a discriminating rule, every active member resolves to the same
        # answer and the per-member subject below just reruns that one decision. Stay in SQL.
        if not has_discriminating_rules:
            default_row = next(
                (row for row in team_rows if row.organization_member_id is None and row.role_id is None), None
            )
            default_level = default_row.access_level if default_row else None
            if default_level in (None, "member", "admin"):
                # No default rule falls through to the facade's admin default; "member"/"admin"
                # default rules grant access to every active org member.
                member_user_ids = member_queryset.values_list("user_id", flat=True)
            else:
                # Default "none" denies every member; only org admins and owners pass the
                # subject's admin bypass.
                member_user_ids = member_queryset.filter(level__gte=OrganizationMembership.Level.ADMIN).values_list(
                    "user_id", flat=True
                )
            return User.objects.filter(is_active=True, id__in=member_user_ids)

        # General case: resolve each active member through `SubjectAccessControl`, seeding its
        # pool from the single team-rules fetch so N subjects share one query rather than running
        # N of them. Only load the user columns subject resolution actually reads (its id).
        memberships = list(
            member_queryset.filter(user__is_active=True)
            .select_related("user")
            .only("id", "user_id", "level", "user__id")
        )

        # Roles the facade uses to resolve each user. User-keyed rather than keyed on the
        # `organization_member` FK because that FK is NULL on legacy `RoleMembership` rows, so
        # the enforced API gate (which goes through `user.role_memberships`) would honor a role
        # rule we would silently drop and the two resolvers would disagree. Only roles a project
        # rule names here can change an answer, so filter at the query to that set.
        named_role_ids = {row.role_id for row in team_rows if row.role_id is not None}
        role_ids_by_user: dict[int, list[str]] = defaultdict(list)
        if role_based_access_supported and named_role_ids:
            role_lookup_user_ids: list[int] = [m.user_id for m in memberships]
            for user_id, role_id in (
                RoleMembership.objects.filter(
                    user_id__in=role_lookup_user_ids,
                    role_id__in=named_role_ids,
                    role__organization_id=self.organization_id,
                )
                .valid_for_authorization()
                .values_list("user_id", "role_id")
            ):
                role_ids_by_user[user_id].append(str(role_id))

        user_ids: list[int] = []
        for membership in memberships:
            # Seed the organization that `SubjectAccessControl.rbac_supported` reads so each
            # subject does not re-fetch the one organization every membership here already lives in.
            membership.organization = organization
            subject = SubjectAccessControl(
                user=membership.user,
                team=self,
                org_membership=membership,
                member=membership,
            )
            subject.preload_access_controls(team_rows, subject_role_ids=role_ids_by_user.get(membership.user_id, []))
            if subject.has_project_access:
                user_ids.append(membership.user_id)
        return User.objects.filter(id__in=user_ids)

    def __str__(self):
        if self.name:
            return self.name
        if self.app_urls and self.app_urls[0]:
            return ", ".join(self.app_urls)
        return str(self.pk)

    __repr__ = sane_repr("id", "uuid", "project_id", "name", "api_token")


@mutable_receiver(post_save, sender=Team)
def put_team_in_cache_on_save(sender, instance: Team, **kwargs):
    set_team_in_cache(instance.api_token, instance)


@mutable_receiver(post_delete, sender=Team)
def delete_team_in_cache_on_delete(sender, instance: Team, **kwargs):
    set_team_in_cache(instance.api_token, None)


@mutable_receiver(post_save, sender=Team)
def reevaluate_authorized_urls_health(sender, instance: Team, **kwargs):
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "app_urls" not in update_fields:
        return

    from posthog.tasks.health_checks import evaluate_health_check_for_team

    team_id = instance.id
    transaction.on_commit(lambda: evaluate_health_check_for_team.delay("authorized_urls", team_id))


def check_is_feature_available_for_team(team_id: int, feature_key: str, current_usage: Optional[int] = None):
    available_product_features: Optional[list[dict[str, str]]] = (
        Team.objects.select_related("organization")
        .values_list("organization__available_product_features", flat=True)
        .get(id=team_id)
    )
    if available_product_features is None:
        return False

    for feature in available_product_features:
        if feature.get("key") == feature_key:
            if current_usage is not None and feature.get("limit") is not None:
                return current_usage < int(feature["limit"])
            return True
    return False
