"""Core project settings serializers and field definitions."""

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models import Team, TeamRevenueAnalyticsConfig
from posthog.models.filters.utils import validate_group_type_index
from posthog.models.integration.email import SANDBOX_EMAIL_PROVIDER

from products.access_control.backend.presentation.access_control import UserAccessControlSerializerMixin
from products.customer_analytics.backend.facade.account_property_pins import (
    InvalidPinnedAccountProperties,
    validate_pinned_account_properties,
)
from products.customer_analytics.backend.facade.contracts import PinnedAccountProperty
from products.customer_analytics.backend.facade.enums import AccountPropertyPinKind
from products.customer_analytics.backend.facade.team_extension import TeamCustomerAnalyticsConfig
from products.feature_flags.backend.facade.request_blocklist import (
    MAX_BLOCKED_HOSTS,
    MAX_BLOCKED_IPS,
    MAX_BLOCKLIST_INPUT_ENTRIES,
    MIN_BLOCKED_IPV4_PREFIX,
    MIN_BLOCKED_IPV6_PREFIX,
    BlocklistEntryError,
    normalize_blocked_hosts,
    normalize_blocked_ips,
)
from products.feature_flags.backend.models.team_feature_flag_policy_config import TeamFeatureFlagPolicyConfig
from products.replay_vision.backend.facade.workflow_scan_limits import (
    MAX_SELF_SERVE_WORKFLOW_SCAN_RATE_CAP_PER_DAY,
    MAX_SELF_SERVE_WORKFLOW_SCAN_TEAM_RATE_CAP_PER_DAY,
    WORKFLOW_SCAN_RATE_CAP_PER_DAY,
    WORKFLOW_SCAN_TEAM_RATE_CAP_PER_DAY,
)
from products.tasks.backend.facade.workflow_tasks import (
    MAX_SELF_SERVE_WORKFLOW_TASK_RATE_CAP_PER_DAY,
    MAX_SELF_SERVE_WORKFLOW_TASK_TEAM_RATE_CAP_PER_DAY,
    WORKFLOW_TASK_RATE_CAP_PER_DAY,
    WORKFLOW_TASK_TEAM_RATE_CAP_PER_DAY,
)
from products.workflows.backend.facade.enums import EMAIL_TRACKING_CONSENT_MODE_CHOICES
from products.workflows.backend.facade.team_extension import TeamWorkflowsConfig


class CachingTeamSerializer(serializers.ModelSerializer):
    """
    This serializer is used for caching teams.
    Currently used only in `/decide` endpoint.
    Has all parameters needed for a successful decide request.
    """

    organization_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Team
        fields = [
            "id",
            "project_id",
            "organization_id",
            "uuid",
            "name",
            "api_token",
            "autocapture_opt_out",
            "autocapture_exceptions_opt_in",
            "autocapture_web_vitals_opt_in",
            "autocapture_web_vitals_allowed_metrics",
            "autocapture_exceptions_errors_to_ignore",
            "capture_performance_opt_in",
            "capture_console_log_opt_in",
            "extra_settings",
            "secret_api_token",
            "secret_api_token_backup",
            "session_recording_opt_in",
            "session_recording_sample_rate",
            "session_recording_minimum_duration_milliseconds",
            "session_recording_linked_flag",
            "session_recording_network_payload_capture_config",
            "session_recording_masking_config",
            "session_recording_url_trigger_config",
            "session_recording_url_blocklist_config",
            "session_recording_event_trigger_config",
            "session_recording_trigger_match_type_config",
            "session_replay_config",
            "survey_config",
            "recording_domains",
            "inject_web_apps",
            "surveys_opt_in",
            "heatmaps_opt_in",
            "capture_dead_clicks",
            "flags_persistence_default",
            "conversations_enabled",
            "conversations_settings",
            "logs_settings",
        ]
        read_only_fields = fields


TEAM_CONFIG_FIELDS = (
    "app_urls",
    "anonymize_ips",
    "completed_snippet_onboarding",
    "test_account_filters",
    "test_account_filters_default_checked",
    "path_cleaning_filters",
    "is_demo",
    "timezone",
    "data_attributes",
    "person_display_name_properties",
    "autocapture_opt_out",
    "autocapture_exceptions_opt_in",
    "autocapture_web_vitals_opt_in",
    "autocapture_web_vitals_allowed_metrics",
    "autocapture_exceptions_errors_to_ignore",
    "capture_console_log_opt_in",
    "logs_settings",
    "capture_performance_opt_in",
    "session_recording_opt_in",
    "session_recording_sample_rate",
    "session_recording_minimum_duration_milliseconds",
    "session_recording_linked_flag",
    "session_recording_network_payload_capture_config",
    "session_recording_masking_config",
    "session_recording_url_trigger_config",
    "session_recording_url_blocklist_config",
    "session_recording_event_trigger_config",
    "session_recording_trigger_match_type_config",
    "session_recording_trigger_groups",
    "session_recording_retention_period",
    "session_replay_config",
    "survey_config",
    "week_start_day",
    "primary_dashboard",
    "home_tab_dashboard",
    "live_events_columns",
    "recording_domains",
    "cookieless_server_hash_mode",
    "human_friendly_comparison_periods",
    "inject_web_apps",
    "extra_settings",
    "modifiers",
    "has_completed_onboarding_for",
    "surveys_opt_in",
    "heatmaps_opt_in",
    "flags_persistence_default",
    "feature_flag_confirmation_enabled",
    "feature_flag_confirmation_message",
    "default_evaluation_contexts_enabled",
    "require_evaluation_contexts",
    "feature_flag_policy_config",
    "capture_dead_clicks",
    "default_data_theme",
    "revenue_analytics_config",
    "marketing_analytics_config",
    "customer_analytics_config",
    "onboarding_tasks",
    "base_currency",
    "web_analytics_pre_aggregated_tables_enabled",
    "receive_org_level_activity_logs",
    "business_model",
    "conversations_enabled",
    "conversations_settings",
    "proactive_tasks_enabled",
    "workflows_config",
)

TEAM_CONFIG_FIELDS_SET = set(TEAM_CONFIG_FIELDS)

TEAM_CONFIG_MEMBER_FIELDS = (
    "completed_snippet_onboarding",
    "has_completed_onboarding_for",
    "onboarding_tasks",
    "session_recording_opt_in",
    "autocapture_exceptions_opt_in",
    "autocapture_web_vitals_opt_in",
    "autocapture_web_vitals_allowed_metrics",
    "surveys_opt_in",
    "primary_dashboard",
    "home_tab_dashboard",
)

TEAM_CONFIG_MEMBER_FIELDS_SET = set(TEAM_CONFIG_MEMBER_FIELDS)

TEAM_CONFIG_ADMIN_FIELDS_SET: set[str] = (TEAM_CONFIG_FIELDS_SET - TEAM_CONFIG_MEMBER_FIELDS_SET) | {
    "is_demo",
    "app_urls",
    "access_control",
    "logo_media",
    # Renaming a project/environment is admin-only (the settings UI gates TeamDisplayName behind
    # useRestrictedArea(Admin)). Excluded from the create-time gate below so members allowed to
    # create projects can still name them.
    "name",
}

# Fields that are not member-safe but carry their own `field_access_control` (enforced in
# UserAccessControlSerializerMixin.validate). The request-level scope can be downgraded for these so
# the field-level check is the real authority — e.g. `app_urls` is governed by web_analytics:editor.
TEAM_CONFIG_FIELD_ACCESS_CONTROLLED_FIELDS: set[str] = {"app_urls"}


class TeamRevenueAnalyticsConfigSerializer(serializers.ModelSerializer, UserAccessControlSerializerMixin):
    events = serializers.JSONField(required=False)
    filter_test_accounts = serializers.BooleanField(required=False)

    class Meta:
        model = TeamRevenueAnalyticsConfig
        fields = ["base_currency", "events", "filter_test_accounts"]

    def to_representation(self, instance):
        repr = super().to_representation(instance)
        if instance.events:
            repr["events"] = [event.model_dump() for event in instance.events]
        return repr

    def to_internal_value(self, data):
        internal_value = super().to_internal_value(data)
        if "events" in internal_value:
            internal_value["_events"] = internal_value["events"]
        return internal_value


class EmailUtmParamsSerializer(serializers.Serializer):
    utm_source = serializers.CharField(
        required=False, allow_blank=True, max_length=500, help_text="Default utm_source. Supports Liquid variables."
    )
    utm_medium = serializers.CharField(
        required=False, allow_blank=True, max_length=500, help_text="Default utm_medium. Supports Liquid variables."
    )
    utm_campaign = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Default utm_campaign. Empty uses the broadcast or workflow name. Supports Liquid variables.",
    )
    utm_content = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Default utm_content. Empty uses the email step name. Supports Liquid variables.",
    )


@extend_schema_field(EmailUtmParamsSerializer)
class EmailUtmParamsField(serializers.JSONField):
    def to_internal_value(self, data: Any) -> dict[str, str]:
        # The value replaces the saved defaults, so a misspelled key would otherwise clear them silently.
        if isinstance(data, dict) and (unknown := sorted(set(data) - set(EmailUtmParamsSerializer().fields))):
            raise serializers.ValidationError(f"Unknown UTM parameters: {', '.join(unknown)}.")
        serializer = EmailUtmParamsSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return {key: value for key, value in serializer.validated_data.items() if value.strip()}


def drop_cached_workflows_config(team: Team) -> None:
    # The config save writes every column, so a row this team instance loaded earlier would undo
    # settings another admin changed since.
    team.__dict__.pop(Team.workflows_config.cache_name, None)


class TeamWorkflowsConfigSerializer(serializers.ModelSerializer, UserAccessControlSerializerMixin):
    capture_workflows_engagement_events = serializers.BooleanField(
        required=False,
        help_text=(
            "When enabled, workflows engagement activity (email sends, opens, clicks, bounces, "
            "spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_*) "
            "alongside the existing workflow metrics."
        ),
    )
    email_tracking_consent_mode = serializers.ChoiceField(
        choices=EMAIL_TRACKING_CONSENT_MODE_CHOICES,
        required=False,
        help_text=(
            "Recipient-consent enforcement for open/click tracking on marketing workflow emails. "
            "'off': no enforcement, tracking follows each email step's own setting. "
            "'opt_out': track by default but not recipients who have opted out. "
            "'opt_in': only track recipients who have explicitly opted in. "
            "Transactional emails are exempt from consent enforcement."
        ),
    )
    workflow_task_rate_limit_per_day = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text=(
            "How many AI tasks one workflow can create in a rolling 24 hours. "
            f"Null uses the default of {WORKFLOW_TASK_RATE_CAP_PER_DAY}; zero pauses task creation "
            f"for every workflow in the project. Support raises the limit above "
            f"{MAX_SELF_SERVE_WORKFLOW_TASK_RATE_CAP_PER_DAY}."
        ),
    )
    workflow_task_team_rate_limit_per_day = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text=(
            "How many AI tasks all workflows in the project can create together in a rolling "
            f"24 hours. Null uses the default of {WORKFLOW_TASK_TEAM_RATE_CAP_PER_DAY}; zero pauses "
            f"task creation for the project. Support raises the limit above "
            f"{MAX_SELF_SERVE_WORKFLOW_TASK_TEAM_RATE_CAP_PER_DAY}."
        ),
    )
    marketing_frequency_cap_max_messages = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=1000,
        help_text=(
            "Most marketing messages one person can get in the window, across all workflows. "
            "Set this together with marketing_frequency_cap_window_days. Set both to null to turn the cap off."
        ),
    )
    marketing_frequency_cap_window_days = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=30,
        help_text=(
            "Length of the rolling frequency cap window in days. "
            "Set this together with marketing_frequency_cap_max_messages. Set both to null to turn the cap off."
        ),
    )

    replay_vision_scan_rate_limit_per_day = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text=(
            "How many Replay Vision scans one workflow can request in a rolling 24 hours. "
            f"Null uses the default of {WORKFLOW_SCAN_RATE_CAP_PER_DAY}; zero pauses scans "
            f"for every workflow in the project. Support raises the limit above "
            f"{MAX_SELF_SERVE_WORKFLOW_SCAN_RATE_CAP_PER_DAY}."
        ),
    )
    replay_vision_scan_team_rate_limit_per_day = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text=(
            "How many Replay Vision scans all workflows in the project request together in a rolling "
            f"24 hours. Null uses the default of {WORKFLOW_SCAN_TEAM_RATE_CAP_PER_DAY}; zero pauses "
            f"scans for the project. Support raises the limit above "
            f"{MAX_SELF_SERVE_WORKFLOW_SCAN_TEAM_RATE_CAP_PER_DAY}."
        ),
    )
    default_email_integration_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text=(
            "ID of the verified email integration that new broadcasts and workflow email steps use as "
            "their sender. Null means no default. Set automatically when the project's first email "
            "sender is verified, and cleared when that integration is deleted."
        ),
    )

    email_utm_tags_enabled = serializers.BooleanField(
        required=False,
        help_text=(
            "Whether new email steps and broadcasts start with UTM tags on their links. "
            "Each email can still change it. Existing emails change only through apply_utm_defaults."
        ),
    )
    email_utm_params = EmailUtmParamsField(
        required=False,
        help_text=(
            "Default UTM values that new email steps and broadcasts copy. An empty value keeps the "
            "built-in default for that tag."
        ),
    )

    class Meta:
        model = TeamWorkflowsConfig
        fields = [
            "capture_workflows_engagement_events",
            "email_tracking_consent_mode",
            "email_utm_tags_enabled",
            "email_utm_params",
            "workflow_task_rate_limit_per_day",
            "workflow_task_team_rate_limit_per_day",
            "replay_vision_scan_rate_limit_per_day",
            "replay_vision_scan_team_rate_limit_per_day",
            "default_email_integration_id",
            "marketing_frequency_cap_max_messages",
            "marketing_frequency_cap_window_days",
        ]

    def _enforce_self_serve_ceiling(self, field: str, value: int | None, ceiling: int) -> int | None:
        # As a nested field there is no stored row to compare against; the parent serializer
        # re-runs this serializer bound to the row in validate_workflows_config.
        if self.parent:
            return value
        # Support raises a project past the ceiling in Django admin; clients that echo the whole
        # config must be able to send that value back unchanged.
        if value is not None and value > ceiling:
            stored = getattr(self.instance, field, None)
            if stored != value:
                raise serializers.ValidationError(f"Contact support to go above {ceiling} tasks a day.")
        return value

    def validate_workflow_task_rate_limit_per_day(self, value: int | None) -> int | None:
        return self._enforce_self_serve_ceiling(
            "workflow_task_rate_limit_per_day", value, MAX_SELF_SERVE_WORKFLOW_TASK_RATE_CAP_PER_DAY
        )

    def validate_workflow_task_team_rate_limit_per_day(self, value: int | None) -> int | None:
        return self._enforce_self_serve_ceiling(
            "workflow_task_team_rate_limit_per_day", value, MAX_SELF_SERVE_WORKFLOW_TASK_TEAM_RATE_CAP_PER_DAY
        )

    def validate_replay_vision_scan_rate_limit_per_day(self, value: int | None) -> int | None:
        return self._enforce_self_serve_ceiling(
            "replay_vision_scan_rate_limit_per_day", value, MAX_SELF_SERVE_WORKFLOW_SCAN_RATE_CAP_PER_DAY
        )

    def validate_replay_vision_scan_team_rate_limit_per_day(self, value: int | None) -> int | None:
        return self._enforce_self_serve_ceiling(
            "replay_vision_scan_team_rate_limit_per_day", value, MAX_SELF_SERVE_WORKFLOW_SCAN_TEAM_RATE_CAP_PER_DAY
        )

    def validate_default_email_integration_id(self, value: int | None) -> int | None:
        if self.parent or value is None:
            return value
        sender = None
        if self.instance is not None:
            try:
                sender = IntegrationManager.email.credentials.get(self.instance.team_id, value)
            except IntegrationNotFound:
                pass
        if sender is None:
            raise serializers.ValidationError("Choose an email sender from this project.")
        if sender.config.get("provider") == SANDBOX_EMAIL_PROVIDER:
            raise serializers.ValidationError(
                "The sandbox sender can't be the project default. Choose a sender on your own verified domain."
            )
        if not sender.config.get("verified"):
            raise serializers.ValidationError("Verify this sender's domain before making it the default.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # As a nested field of the team serializer there is no stored row to merge a partial update with.
        # validate_team_workflows_config runs this serializer again with the row, and that run does the check.
        if self.parent:
            return attrs
        cap_fields = ("marketing_frequency_cap_max_messages", "marketing_frequency_cap_window_days")
        cap = {field: attrs[field] for field in cap_fields if field in attrs}
        if len(cap) == 1 and self.instance is not None:
            cap = {field: cap.get(field, getattr(self.instance, field)) for field in cap_fields}
        # The worker treats either null as no cap, so a half-set cap would save but never apply.
        if cap:
            missing = [field for field in cap_fields if cap.get(field) is None]
            if len(missing) == 1:
                other = next(field for field in cap_fields if field != missing[0])
                raise serializers.ValidationError(
                    {missing[0]: f"Set this together with {other}, or set both to null to turn the frequency cap off."}
                )
        return attrs


class TeamFeatureFlagPolicyConfigSerializer(serializers.ModelSerializer, UserAccessControlSerializerMixin):
    require_tags = serializers.BooleanField(
        required=False,
        help_text=(
            "When enabled, a new feature flag needs at least one tag, and a tagged flag cannot lose its "
            "last one. A create that declares it comes from a survey, experiment, early access feature, "
            "product tour, or web experiment is exempt, because those forms have no tag input. The caller "
            "sets that declaration, so a flag can still be created without a tag."
        ),
    )

    # allow_blank lets a client send a list split from pasted lines, because the normalizers drop blank entries.
    # The normalizers own the MAX_BLOCKED_* caps, because they count entries after dropping blanks and duplicates.
    blocked_hosts = serializers.ListField(
        child=serializers.CharField(max_length=2000, allow_blank=True),
        max_length=MAX_BLOCKLIST_INPUT_ENTRIES,
        required=False,
        help_text=(
            f"Domains to block from feature flag requests (/flags and /decide), up to {MAX_BLOCKED_HOSTS}. "
            "A domain also covers its subdomains. It is compared with the Origin header, or with the Referer "
            "header when Origin is missing. Entries are stored lowercase without duplicates. A pasted URL is "
            "reduced to its domain, and an internationalized domain is stored as punycode."
        ),
    )
    blocked_ips = serializers.ListField(
        child=serializers.CharField(max_length=2000, allow_blank=True),
        max_length=MAX_BLOCKLIST_INPUT_ENTRIES,
        required=False,
        help_text=(
            f"IPv4 or IPv6 addresses or CIDR ranges to block from feature flag requests (/flags and /decide), "
            f"up to {MAX_BLOCKED_IPS}. Ranges can be /{MIN_BLOCKED_IPV4_PREFIX} or narrower for IPv4 and "
            f"/{MIN_BLOCKED_IPV6_PREFIX} or narrower for IPv6. Entries are stored in canonical form without "
            "duplicates, and an IPv4-mapped IPv6 address is stored as IPv4."
        ),
    )

    class Meta:
        model = TeamFeatureFlagPolicyConfig
        fields = ["require_tags", "blocked_hosts", "blocked_ips"]

    def validate_blocked_hosts(self, value: list[str]) -> list[str]:
        try:
            return normalize_blocked_hosts(value)
        except BlocklistEntryError as error:
            raise serializers.ValidationError(str(error))

    def validate_blocked_ips(self, value: list[str]) -> list[str]:
        try:
            return normalize_blocked_ips(value)
        except BlocklistEntryError as error:
            raise serializers.ValidationError(str(error))


class TeamCustomerAnalyticsPinnedAccountPropertySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=AccountPropertyPinKind.choices,
        help_text=(
            "Type of this default pinned account property: a custom property, a relationship, "
            "or a built-in account field."
        ),
    )
    id = serializers.CharField(
        max_length=64,
        help_text=(
            "Project-scoped custom property or relationship definition UUID. "
            "For an account_field pin, the account field name, such as stripe_customer_id."
        ),
    )

    class Meta:
        ref_name = "TeamCustomerAnalyticsPinnedAccountProperty"


class TeamCustomerAnalyticsConfigSerializer(serializers.ModelSerializer, UserAccessControlSerializerMixin):
    activity_event = serializers.JSONField(required=False, help_text="Event used as the activity signal (DAU/WAU/MAU).")
    signup_pageview_event = serializers.JSONField(
        required=False, help_text="Event used to count signup pageviews on dashboards."
    )
    signup_event = serializers.JSONField(required=False, help_text="Event used to count signups on dashboards.")
    subscription_event = serializers.JSONField(
        required=False, help_text="Event used to count subscriptions on dashboards."
    )
    payment_event = serializers.JSONField(required=False, help_text="Event used to count payments on dashboards.")
    account_group_type_index = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text=(
            "Index of the group type to treat as an Account in customer analytics. "
            "Must reference an existing group type configured for the project."
        ),
    )
    default_pinned_properties = TeamCustomerAnalyticsPinnedAccountPropertySerializer(
        many=True,
        allow_empty=True,
        required=False,
        help_text=(
            "Ordered account properties shown until a user saves a personal pinned-property selection. "
            "Pass an empty list to show no properties by default."
        ),
    )

    class Meta:
        model = TeamCustomerAnalyticsConfig
        fields = [
            "activity_event",
            "signup_pageview_event",
            "signup_event",
            "subscription_event",
            "payment_event",
            "account_group_type_index",
            "default_pinned_properties",
        ]

    def update(
        self, instance: TeamCustomerAnalyticsConfig, validated_data: dict[str, Any]
    ) -> TeamCustomerAnalyticsConfig:
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        # The account track rules on this row are written by their own path, so a settings save must
        # not carry a stale copy of them back to the database.
        instance.save(update_fields=list(validated_data))
        return instance

    @staticmethod
    def validate_account_group_type_index(value):
        return validate_group_type_index("account_group_type_index", value)

    def validate_default_pinned_properties(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.instance is None:
            return value
        try:
            pinned_properties = validate_pinned_account_properties(
                team_id=self.instance.team_id,
                pinned_properties=[
                    PinnedAccountProperty(kind=reference["kind"], id=reference["id"]) for reference in value
                ],
            )
        except InvalidPinnedAccountProperties as error:
            raise serializers.ValidationError(error.errors)
        return [{"kind": reference.kind, "id": reference.id} for reference in pinned_properties]
