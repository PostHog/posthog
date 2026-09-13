"""Core project settings serializers and field definitions."""

from rest_framework import serializers

from posthog.models import Team, TeamRevenueAnalyticsConfig
from posthog.models.filters.utils import validate_group_type_index

from products.access_control.backend.presentation.access_control import UserAccessControlSerializerMixin
from products.customer_analytics.backend.facade.team_extension import TeamCustomerAnalyticsConfig
from products.feature_flags.backend.models.team_feature_flag_policy_config import TeamFeatureFlagPolicyConfig
from products.workflows.backend.models.team_workflows_config import EmailTrackingConsentMode, TeamWorkflowsConfig


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
    "correlation_config",
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
)

TEAM_CONFIG_MEMBER_FIELDS_SET = set(TEAM_CONFIG_MEMBER_FIELDS)

TEAM_CONFIG_ADMIN_FIELDS_SET: set[str] = (TEAM_CONFIG_FIELDS_SET - TEAM_CONFIG_MEMBER_FIELDS_SET) | {
    "is_demo",
    "app_urls",
    "access_control",
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
        choices=EmailTrackingConsentMode.choices,
        required=False,
        help_text=(
            "Recipient-consent enforcement for open/click tracking on marketing workflow emails. "
            "'off': no enforcement, tracking follows each email step's own setting. "
            "'opt_out': track by default but not recipients who have opted out. "
            "'opt_in': only track recipients who have explicitly opted in. "
            "Transactional emails are exempt from consent enforcement."
        ),
    )

    class Meta:
        model = TeamWorkflowsConfig
        fields = ["capture_workflows_engagement_events", "email_tracking_consent_mode"]


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

    class Meta:
        model = TeamFeatureFlagPolicyConfig
        fields = ["require_tags"]


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

    class Meta:
        model = TeamCustomerAnalyticsConfig
        fields = [
            "activity_event",
            "signup_pageview_event",
            "signup_event",
            "subscription_event",
            "payment_event",
            "account_group_type_index",
        ]

    @staticmethod
    def validate_account_group_type_index(value):
        return validate_group_type_index("account_group_type_index", value)
