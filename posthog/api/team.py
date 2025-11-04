import json
from datetime import timedelta
from functools import cached_property
from typing import Any, Literal, Optional, cast

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404

from loginas.utils import is_impersonated_session
from rest_framework import exceptions, request, response, serializers, viewsets
from rest_framework.permissions import BasePermission, IsAuthenticated

from posthog.schema import AttributionMode

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import TeamBasicSerializer
from posthog.api.utils import action
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.constants import AvailableFeature
from posthog.event_usage import report_user_action
from posthog.geoip import get_geoip_properties
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import ProductIntent, Team, TeamMarketingAnalyticsConfig, TeamRevenueAnalyticsConfig, User
from posthog.models.activity_logging.activity_log import Detail, dict_changes_between, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.data_color_theme import DataColorTheme
from posthog.models.event_ingestion_restriction_config import EventIngestionRestrictionConfig
from posthog.models.feature_flag import TeamDefaultEvaluationTag
from posthog.models.group_type_mapping import GROUP_TYPE_MAPPING_SERIALIZER_FIELDS, GroupTypeMapping
from posthog.models.organization import OrganizationMembership
from posthog.models.product_intent.product_intent import ProductIntentSerializer, calculate_product_activation
from posthog.models.project import Project
from posthog.models.signals import mute_selected_signals
from posthog.models.tag import Tag
from posthog.models.team.team import CURRENCY_CODE_CHOICES, DEFAULT_CURRENCY
from posthog.models.team.util import actions_that_require_current_team, delete_batch_exports, delete_bulky_postgres_data
from posthog.models.utils import UUIDT
from posthog.permissions import (
    CREATE_ACTIONS,
    AccessControlPermission,
    APIScopePermission,
    OrganizationAdminWritePermissions,
    OrganizationMemberPermissions,
    TeamMemberLightManagementPermission,
    TeamMemberStrictManagementPermission,
)
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.scopes import APIScopeObjectOrNotSupported
from posthog.session_recordings.data_retention import (
    VALID_RETENTION_PERIODS,
    parse_feature_to_entitlement,
    retention_violates_entitlement,
    validate_retention_period,
)
from posthog.user_permissions import UserPermissions, UserPermissionsSerializerMixin
from posthog.utils import get_instance_realm, get_ip_address, get_week_start_for_country_code


def _format_serializer_errors(serializer_errors: dict) -> str:
    """Formats DRF serializer errors into a human readable string."""
    error_messages: list[str] = []
    for field, field_errors in serializer_errors.items():
        if isinstance(field_errors, list):
            error_messages.extend(f"{field}: {error}" for error in field_errors)
        else:
            error_messages.append(f"{field}: {field_errors}")
    return ". ".join(error_messages)


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
        ]
        read_only_fields = fields


TEAM_CONFIG_FIELDS = (
    "app_urls",
    "slack_incoming_webhook",
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
    "default_evaluation_environments_enabled",
    "capture_dead_clicks",
    "default_data_theme",
    "revenue_analytics_config",
    "marketing_analytics_config",
    "onboarding_tasks",
    "base_currency",
    "web_analytics_pre_aggregated_tables_enabled",
    "experiment_recalculation_time",
)

TEAM_CONFIG_FIELDS_SET = set(TEAM_CONFIG_FIELDS)


class TeamRevenueAnalyticsConfigSerializer(serializers.ModelSerializer):
    events = serializers.JSONField(required=False)
    goals = serializers.JSONField(required=False)
    filter_test_accounts = serializers.BooleanField(required=False)

    class Meta:
        model = TeamRevenueAnalyticsConfig
        fields = ["base_currency", "events", "goals", "filter_test_accounts"]

    def to_representation(self, instance):
        repr = super().to_representation(instance)
        if instance.events:
            repr["events"] = [event.model_dump() for event in instance.events]
        if instance.goals:
            repr["goals"] = [goal.model_dump() for goal in instance.goals]
        return repr

    def to_internal_value(self, data):
        internal_value = super().to_internal_value(data)
        if "events" in internal_value:
            internal_value["_events"] = internal_value["events"]
        if "goals" in internal_value:
            internal_value["_goals"] = internal_value["goals"]
        return internal_value


class TeamMarketingAnalyticsConfigSerializer(serializers.ModelSerializer):
    sources_map = serializers.JSONField(required=False)
    conversion_goals = serializers.JSONField(required=False)
    attribution_window_days = serializers.IntegerField(required=False, min_value=1, max_value=90)
    attribution_mode = serializers.ChoiceField(
        choices=[(mode.value, mode.value.replace("_", " ").title()) for mode in AttributionMode], required=False
    )
    campaign_name_mappings = serializers.JSONField(required=False)

    class Meta:
        model = TeamMarketingAnalyticsConfig
        fields = [
            "sources_map",
            "conversion_goals",
            "attribution_window_days",
            "attribution_mode",
            "campaign_name_mappings",
        ]

    def update(self, instance, validated_data):
        # Handle sources_map with partial updates
        if "sources_map" in validated_data:
            new_sources_map = validated_data["sources_map"]

            # For each source in the new data, update it individually
            for source_id, field_mapping in new_sources_map.items():
                if field_mapping is None:
                    # If None is passed, remove the source entirely
                    instance.remove_source_mapping(source_id)
                else:
                    # Update the source mapping (this preserves other sources)
                    instance.update_source_mapping(source_id, field_mapping)

        if "conversion_goals" in validated_data:
            instance.conversion_goals = validated_data["conversion_goals"]

        # Handle attribution settings
        if "attribution_window_days" in validated_data:
            instance.attribution_window_days = validated_data["attribution_window_days"]

        if "attribution_mode" in validated_data:
            instance.attribution_mode = validated_data["attribution_mode"]

        if "campaign_name_mappings" in validated_data:
            instance.campaign_name_mappings = validated_data["campaign_name_mappings"]

        instance.save()
        return instance


class TeamSerializer(serializers.ModelSerializer, UserPermissionsSerializerMixin, UserAccessControlSerializerMixin):
    instance: Optional[Team]

    effective_membership_level = serializers.SerializerMethodField()
    has_group_types = serializers.SerializerMethodField()
    group_types = serializers.SerializerMethodField()
    live_events_token = serializers.SerializerMethodField()
    product_intents = serializers.SerializerMethodField()
    managed_viewsets = serializers.SerializerMethodField()
    revenue_analytics_config = TeamRevenueAnalyticsConfigSerializer(required=False)
    marketing_analytics_config = TeamMarketingAnalyticsConfigSerializer(required=False)
    base_currency = serializers.ChoiceField(choices=CURRENCY_CODE_CHOICES, default=DEFAULT_CURRENCY)

    class Meta:
        model = Team
        fields = (
            "id",
            "uuid",
            "name",
            "access_control",
            "organization",
            "project_id",
            "api_token",
            "secret_api_token",
            "secret_api_token_backup",
            "created_at",
            "updated_at",
            "ingested_event",
            "default_modifiers",
            "person_on_events_querying_enabled",
            "user_access_level",
            # Config fields
            *TEAM_CONFIG_FIELDS,
            # Computed fields
            "effective_membership_level",
            "has_group_types",
            "group_types",
            "live_events_token",
            "product_intents",
            "managed_viewsets",
        )

        read_only_fields = (
            "id",
            "uuid",
            "organization",
            "project_id",
            "api_token",
            "secret_api_token",
            "secret_api_token_backup",
            "created_at",
            "updated_at",
            "ingested_event",
            "effective_membership_level",
            "has_group_types",
            "group_types",
            "default_modifiers",
            "person_on_events_querying_enabled",
            "live_events_token",
            "user_access_level",
            "product_intents",
            "managed_viewsets",
        )

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        # fallback to the default posthog data theme id, if the color feature isn't available e.g. after a downgrade
        if not instance.organization.is_feature_available(AvailableFeature.DATA_COLOR_THEMES):
            representation["default_data_theme"] = (
                DataColorTheme.objects.filter(team_id__isnull=True).values_list("id", flat=True).first()
            )

        return representation

    def get_effective_membership_level(self, team: Team) -> Optional[OrganizationMembership.Level]:
        # TODO: Map from user_access_controls
        return self.user_permissions.team(team).effective_membership_level

    def get_has_group_types(self, team: Team) -> bool:
        return GroupTypeMapping.objects.filter(project_id=team.project_id).exists()

    def get_group_types(self, team: Team) -> list[dict[str, Any]]:
        return list(
            GroupTypeMapping.objects.filter(project_id=team.project_id)
            .order_by("group_type_index")
            .values(*GROUP_TYPE_MAPPING_SERIALIZER_FIELDS)
        )

    def get_live_events_token(self, team: Team) -> Optional[str]:
        return encode_jwt(
            {"team_id": team.id, "api_token": team.api_token},
            timedelta(days=7),
            PosthogJwtAudience.LIVESTREAM,
        )

    def get_product_intents(self, obj):
        calculate_product_activation.delay(obj.id, only_calc_if_days_since_last_checked=1)
        return ProductIntent.objects.filter(team=obj).values(
            "product_type", "created_at", "onboarding_completed_at", "updated_at"
        )

    def get_managed_viewsets(self, obj):
        from products.data_warehouse.backend.models import DataWarehouseManagedViewSet

        enabled_viewsets = DataWarehouseManagedViewSet.objects.filter(team=obj).values_list("kind", flat=True)
        enabled_set = set(enabled_viewsets)

        return {kind: (kind in enabled_set) for kind, _ in DataWarehouseManagedViewSet.Kind.choices}

    @staticmethod
    def validate_revenue_analytics_config(value):
        if value is None:
            return None

        if not isinstance(value, dict):
            raise exceptions.ValidationError("Must provide a dictionary or None.")

        serializer = TeamRevenueAnalyticsConfigSerializer(data=value)
        if not serializer.is_valid():
            raise exceptions.ValidationError(_format_serializer_errors(serializer.errors))

        return serializer.validated_data

    @staticmethod
    def validate_marketing_analytics_config(value):
        if value is None:
            return None

        serializer = TeamMarketingAnalyticsConfigSerializer(data=value)
        if not serializer.is_valid():
            raise exceptions.ValidationError(_format_serializer_errors(serializer.errors))
        return serializer.validated_data

    @staticmethod
    def validate_session_recording_linked_flag(value) -> dict | None:
        if value is None:
            return None

        if not isinstance(value, dict):
            raise exceptions.ValidationError("Must provide a dictionary or None.")
        received_keys = value.keys()
        valid_keys = [
            {"id", "key"},
            {"id", "key", "variant"},
        ]
        if received_keys not in valid_keys:
            raise exceptions.ValidationError(
                "Must provide a dictionary with only 'id' and 'key' keys. _or_ only 'id', 'key', and 'variant' keys."
            )

        return value

    @staticmethod
    def validate_session_recording_trigger_match_type_config(value) -> Literal["all", "any"] | None:
        if value not in ["all", "any", None]:
            raise exceptions.ValidationError(
                "Must provide a valid trigger match type. Only 'all' or 'any' or None are allowed."
            )

        return value

    @staticmethod
    def validate_session_recording_retention_period(value) -> Literal["30d", "90d", "1y", "5y"] | None:
        if not validate_retention_period(value):
            raise exceptions.ValidationError(
                f"Must provide a valid retention period. Options are: {VALID_RETENTION_PERIODS}."
            )

        return value

    @staticmethod
    def validate_session_recording_network_payload_capture_config(value) -> dict | None:
        if value is None:
            return None

        if not isinstance(value, dict):
            raise exceptions.ValidationError("Must provide a dictionary or None.")

        if not all(key in ["recordHeaders", "recordBody"] for key in value.keys()):
            raise exceptions.ValidationError(
                "Must provide a dictionary with only 'recordHeaders' and/or 'recordBody' keys."
            )

        return value

    @staticmethod
    def validate_session_recording_masking_config(value) -> dict | None:
        if value is None:
            return None

        if not isinstance(value, dict):
            raise exceptions.ValidationError("Must provide a dictionary or None.")

        allowed_keys = {"maskAllInputs", "maskTextSelector", "blockSelector"}

        if not all(key in allowed_keys for key in value.keys()):
            raise exceptions.ValidationError(
                f"Must provide a dictionary with only known keys: {', '.join(allowed_keys)}."
            )

        if "maskAllInputs" in value:
            if not isinstance(value["maskAllInputs"], bool):
                raise exceptions.ValidationError("maskAllInputs must be a boolean.")

        if "maskTextSelector" in value:
            if not isinstance(value["maskTextSelector"], str):
                raise exceptions.ValidationError("maskTextSelector must be a string.")

        if "blockSelector" in value:
            if not isinstance(value["blockSelector"], str):
                raise exceptions.ValidationError("blockSelector must be a string.")

        return value

    @staticmethod
    def validate_session_replay_config(value) -> dict | None:
        if value is None:
            return None

        if not isinstance(value, dict):
            raise exceptions.ValidationError("Must provide a dictionary or None.")

        known_keys = ["record_canvas", "ai_config"]
        if not all(key in known_keys for key in value.keys()):
            raise exceptions.ValidationError(
                f"Must provide a dictionary with only known keys. One or more of {', '.join(known_keys)}."
            )

        if "ai_config" in value:
            TeamSerializer.validate_session_replay_ai_summary_config(value["ai_config"])

        return value

    @staticmethod
    def validate_session_replay_ai_summary_config(value: dict | None) -> dict | None:
        if value is not None:
            if not isinstance(value, dict):
                raise exceptions.ValidationError("Must provide a dictionary or None.")

            allowed_keys = [
                "included_event_properties",
                "opt_in",
                "preferred_events",
                "excluded_events",
                "important_user_properties",
            ]
            if not all(key in allowed_keys for key in value.keys()):
                raise exceptions.ValidationError(
                    f"Must provide a dictionary with only allowed keys: {', '.join(allowed_keys)}."
                )

        return value

    def validate_access_control(self, value) -> None:
        """Validate that access_control field is not being used as it's deprecated."""
        if value is not None:
            import posthoganalytics

            request = self.context.get("request")
            user = request.user if request else None

            posthoganalytics.capture_exception(
                Exception("Deprecated access control field used"),
                properties={
                    "field": "access_control",
                    "value": str(value),
                    "user_id": user.id if user else None,
                    "team_id": getattr(user, "team_id", None) if user else None,
                },
            )

            raise exceptions.ValidationError(
                "The 'access_control' field has been deprecated and is no longer supported. "
                "Please use the new access control system instead. "
                "For more information, visit: https://posthog.com/docs/settings/access-control"
            )
        return None

    def validate_app_urls(self, value: list[str | None] | None) -> list[str] | None:
        if value is None:
            return value
        return [url for url in value if url]

    def validate_recording_domains(self, value: list[str | None] | None) -> list[str] | None:
        if value is None:
            return value
        return [domain for domain in value if domain]

    def validate(self, attrs: Any) -> Any:
        attrs = validate_team_attrs(attrs, self.context["view"], self.context["request"], self.instance)
        return super().validate(attrs)

    def create(self, validated_data: dict[str, Any], **kwargs) -> Team:
        request = self.context["request"]
        if self.context["project_id"] not in self.user_permissions.project_ids_visible_for_user:
            raise exceptions.NotFound("Project not found.")
        validated_data["project_id"] = self.context["project_id"]
        serializers.raise_errors_on_nested_writes("create", self, validated_data)

        if "week_start_day" not in validated_data:
            country_code = get_geoip_properties(get_ip_address(request)).get("$geoip_country_code", None)
            if country_code:
                week_start_day_for_user_ip_location = get_week_start_for_country_code(country_code)
                # get_week_start_for_country_code() also returns 6 for countries where the week starts on Saturday,
                # but ClickHouse doesn't support Saturday as the first day of the week, so we fall back to Sunday
                validated_data["week_start_day"] = 1 if week_start_day_for_user_ip_location == 1 else 0

        team = Team.objects.create_with_data(
            initiating_user=request.user,
            organization=self.context["view"].organization,
            **validated_data,
        )

        request.user.current_team = team
        request.user.team = request.user.current_team  # Update cached property
        request.user.save()

        log_activity(
            organization_id=team.organization_id,
            team_id=team.pk,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
            scope="Team",
            item_id=team.pk,
            activity="created",
            detail=Detail(name=str(team.name)),
        )

        return team

    def update(self, instance: Team, validated_data: dict[str, Any]) -> Team:
        before_update = instance.__dict__.copy()

        # Should be validated already, but let's be extra sure
        if config_data := validated_data.pop("revenue_analytics_config", None):
            self._update_revenue_analytics_config(instance, config_data)

        if config_data := validated_data.pop("marketing_analytics_config", None):
            self._update_marketing_analytics_config(instance, config_data)

        if "session_recording_retention_period" in validated_data:
            self._verify_update_session_recording_retention_period(
                instance, validated_data["session_recording_retention_period"]
            )

        if "survey_config" in validated_data:
            if instance.survey_config is not None and validated_data.get("survey_config") is not None:
                validated_data["survey_config"] = {
                    **instance.survey_config,
                    **validated_data["survey_config"],
                }

            if validated_data.get("survey_config") is None:
                del before_update["survey_config"]

            survey_config_changes_between = dict_changes_between(
                "Survey",
                before_update.get("survey_config", {}),
                validated_data.get("survey_config", {}),
                use_field_exclusions=True,
            )

            if survey_config_changes_between:
                log_activity(
                    organization_id=cast(UUIDT, instance.organization_id),
                    team_id=instance.pk,
                    user=cast(User, self.context["request"].user),
                    was_impersonated=is_impersonated_session(request),
                    scope="Survey",
                    item_id="",
                    activity="updated",
                    detail=Detail(
                        name="global survey appearance",
                        changes=survey_config_changes_between,
                    ),
                )

        if (
            "session_replay_config" in validated_data
            and validated_data["session_replay_config"] is not None
            and instance.session_replay_config is not None
        ):
            # for session_replay_config and its top level keys we merge existing settings with new settings
            # this way we don't always have to receive the entire settings object to change one setting
            # so for each key in validated_data["session_replay_config"] we merge it with the existing settings
            # and then merge any top level keys that weren't provided

            for key, value in validated_data["session_replay_config"].items():
                if key in instance.session_replay_config:
                    # if they're both dicts then we merge them, otherwise, the new value overwrites the old
                    if isinstance(instance.session_replay_config[key], dict) and isinstance(
                        validated_data["session_replay_config"][key], dict
                    ):
                        validated_data["session_replay_config"][key] = {
                            **instance.session_replay_config[key],  # existing values
                            **value,  # and new values on top
                        }

            # then also add back in any keys that exist but are not in the provided data
            validated_data["session_replay_config"] = {
                **instance.session_replay_config,
                **validated_data["session_replay_config"],
            }

        updated_team = super().update(instance, validated_data)
        changes = dict_changes_between("Team", before_update, updated_team.__dict__, use_field_exclusions=True)

        log_activity(
            organization_id=cast(UUIDT, instance.organization_id),
            team_id=instance.pk,
            user=cast(User, self.context["request"].user),
            was_impersonated=is_impersonated_session(request),
            scope="Team",
            item_id=instance.pk,
            activity="updated",
            detail=Detail(
                name=str(instance.name),
                changes=changes,
            ),
        )

        return updated_team

    def _update_revenue_analytics_config(self, instance: Team, validated_data: dict[str, Any]) -> Team:
        # Capture old config before saving
        old_config = {
            "events": [event.model_dump() for event in (instance.revenue_analytics_config.events or [])],
            "goals": [goal.model_dump() for goal in (instance.revenue_analytics_config.goals or [])],
            "filter_test_accounts": instance.revenue_analytics_config.filter_test_accounts,
        }

        serializer = TeamRevenueAnalyticsConfigSerializer(
            instance.revenue_analytics_config, data=validated_data, partial=True
        )
        if not serializer.is_valid():
            raise serializers.ValidationError(_format_serializer_errors(serializer.errors))

        serializer.save()

        # Log activity for revenue analytics config changes
        new_config = {
            "events": validated_data.get("events", []),
            "goals": validated_data.get("goals", []),
            "filter_test_accounts": validated_data.get("filter_test_accounts", False),
        }

        self._capture_diff(instance, "revenue_analytics_config", old_config, new_config)

        if "events" in validated_data:
            from products.data_warehouse.backend.models import DataWarehouseManagedViewSet

            managed_viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
                team=instance,
                kind=DataWarehouseManagedViewSet.Kind.REVENUE_ANALYTICS,
            )
            managed_viewset.sync_views()

        return instance

    def _update_marketing_analytics_config(self, instance: Team, validated_data: dict[str, Any]) -> Team:
        # Capture the old config before saving
        old_config = {
            "sources_map": (
                instance.marketing_analytics_config.sources_map.copy()
                if instance.marketing_analytics_config.sources_map
                else {}
            ),
            "attribution_window_days": instance.marketing_analytics_config.attribution_window_days,
            "attribution_mode": instance.marketing_analytics_config.attribution_mode,
            # Add other fields as they're added to the model
            # "conversion_goals": instance.marketing_analytics_config.conversion_goals.copy() if instance.marketing_analytics_config.conversion_goals else [],
        }

        marketing_serializer = TeamMarketingAnalyticsConfigSerializer(
            instance.marketing_analytics_config, data=validated_data, partial=True
        )
        if not marketing_serializer.is_valid():
            raise serializers.ValidationError(_format_serializer_errors(marketing_serializer.errors))

        marketing_serializer.save()

        # Log activity for marketing analytics config changes
        new_config = {
            "sources_map": validated_data.get("sources_map", {}),
            "attribution_window_days": validated_data.get("attribution_window_days"),
            "attribution_mode": validated_data.get("attribution_mode"),
            # Add other fields as they're added to the model
            # "conversion_goals": validated_data.get("conversion_goals", []),
        }

        self._capture_diff(instance, "marketing_analytics_config", old_config, new_config)
        return instance

    def _verify_update_session_recording_retention_period(self, instance: Team, new_retention_period: str):
        retention_feature = instance.organization.get_available_feature(AvailableFeature.SESSION_REPLAY_DATA_RETENTION)
        highest_retention_entitlement = parse_feature_to_entitlement(retention_feature)

        if highest_retention_entitlement is None:
            raise exceptions.APIException(detail="Invalid retention entitlement.")  # HTTP 500

        # Should be validated already, but let's be extra sure to avoid IndexErrors below
        if not validate_retention_period(new_retention_period):
            raise exceptions.ValidationError(  # HTTP 400
                f"Must provide a valid retention period. Options are: {VALID_RETENTION_PERIODS}."
            )

        if retention_violates_entitlement(new_retention_period, highest_retention_entitlement):
            raise exceptions.PermissionDenied(  # HTTP 403
                f"This organization does not have permission to set retention period of length '{new_retention_period}' - longest allowable retention period is '{highest_retention_entitlement}'."
            )

    def _capture_diff(self, instance: Team, key: str, before: dict, after: dict):
        changes = dict_changes_between(
            "Team",
            {key: before},
            {key: after},
            use_field_exclusions=True,
        )

        if changes:
            log_activity(
                organization_id=cast(UUIDT, instance.organization_id),
                team_id=instance.pk,
                user=cast(User, self.context["request"].user),
                was_impersonated=is_impersonated_session(request),
                scope="Team",
                item_id=instance.pk,
                activity="updated",
                detail=Detail(name=str(instance.name), changes=changes),
            )


class TeamViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    """
    Projects for the current organization.
    """

    scope_object: APIScopeObjectOrNotSupported = "project"  # TODO: Change to `environment` on environments rollout
    serializer_class = TeamSerializer
    queryset = Team.objects.all().select_related("organization")
    lookup_field = "id"
    ordering = "-created_by"

    def safely_get_queryset(self, queryset):
        user = cast(User, self.request.user)
        # IMPORTANT: This is actually what ensures that a user cannot read/update a project for which they don't have permission
        visible_teams_ids = UserPermissions(user).team_ids_visible_for_user
        queryset = queryset.filter(id__in=visible_teams_ids)
        if isinstance(self.request.successful_authenticator, PersonalAPIKeyAuthentication):
            if scoped_organizations := self.request.successful_authenticator.personal_api_key.scoped_organizations:
                queryset = queryset.filter(project__organization_id__in=scoped_organizations)
            if scoped_teams := self.request.successful_authenticator.personal_api_key.scoped_teams:
                queryset = queryset.filter(id__in=scoped_teams)
        if isinstance(self.request.successful_authenticator, OAuthAccessTokenAuthentication):
            if scoped_organizations := self.request.successful_authenticator.access_token.scoped_organizations:
                queryset = queryset.filter(project__organization_id__in=scoped_organizations)
            if scoped_teams := self.request.successful_authenticator.access_token.scoped_teams:
                queryset = queryset.filter(id__in=scoped_teams)
        return queryset

    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        if self.action == "list":
            return TeamBasicSerializer
        return super().get_serializer_class()

    def dangerously_get_required_scopes(self, request, view) -> list[str] | None:
        # Used for the AccessControlViewSetMixin
        mixin_result = super().dangerously_get_required_scopes(request, view)
        if mixin_result is not None:
            return mixin_result

        # If the request only contains config fields, require read:team scope
        # Otherwise, require write:team scope (handled by APIScopePermission)
        if self.action == "partial_update":
            request_fields = set(request.data.keys())
            non_team_config_fields = request_fields - TEAM_CONFIG_FIELDS_SET
            if not non_team_config_fields:
                return ["project:read"]

        # Fall back to the default behavior
        return None

    # NOTE: Team permissions are somewhat complex so we override the underlying viewset's get_permissions method
    def dangerously_get_permissions(self) -> list:
        """
        Special permissions handling for create requests as the organization is inferred from the current user.
        """

        permissions: list = [
            IsAuthenticated,
            APIScopePermission,
            AccessControlPermission,
            PremiumMultiEnvironmentPermission,
            *self.permission_classes,
        ]

        # Return early for non-actions (e.g. OPTIONS)
        if self.action:
            if self.action == "create":
                if "is_demo" not in self.request.data or not self.request.data["is_demo"]:
                    permissions.append(OrganizationAdminWritePermissions)
                else:
                    permissions.append(OrganizationMemberPermissions)
            elif self.action != "list":
                # Skip TeamMemberAccessPermission for list action, as list is serialized with limited TeamBasicSerializer
                permissions.append(TeamMemberLightManagementPermission)

        return [permission() for permission in permissions]

    def safely_get_object(self, queryset):
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@current":
            team = getattr(self.request.user, "team", None)
            if team is None:
                raise exceptions.NotFound()
            return team

        filter_kwargs = {self.lookup_field: lookup_value}
        try:
            team = get_object_or_404(queryset, **filter_kwargs)
        except ValueError as error:
            raise exceptions.ValidationError(str(error))
        return team

    # :KLUDGE: Exposed for compatibility reasons for permission classes.
    @property
    def team(self):
        return self.get_object()

    def perform_destroy(self, team: Team):
        # Check if bulk deletion operations are disabled via environment variable
        if settings.DISABLE_BULK_DELETES:
            raise exceptions.ValidationError(
                "Team deletion is temporarily disabled during database migration. Please try again later."
            )

        team_id = team.pk
        organization_id = team.organization_id
        team_name = team.name

        user = cast(User, self.request.user)

        delete_bulky_postgres_data(team_ids=[team_id])
        delete_batch_exports(team_ids=[team_id])

        with mute_selected_signals():
            super().perform_destroy(team)

        # Once the project is deleted, queue deletion of associated data
        AsyncDeletion.objects.bulk_create(
            [
                AsyncDeletion(
                    deletion_type=DeletionType.Team,
                    team_id=team_id,
                    key=str(team_id),
                    created_by=user,
                )
            ],
            ignore_conflicts=True,
        )

        log_activity(
            organization_id=cast(UUIDT, organization_id),
            team_id=team_id,
            user=user,
            was_impersonated=is_impersonated_session(self.request),
            scope="Team",
            item_id=team_id,
            activity="deleted",
            detail=Detail(name=str(team_name)),
        )
        # TRICKY: We pass in `team` here as access to `user.current_team` can fail if it was deleted
        report_user_action(user, f"team deleted", team=team)

    @action(
        methods=["PATCH"],
        detail=True,
        # Only ADMIN or higher users are allowed to access this project
        permission_classes=[TeamMemberStrictManagementPermission],
    )
    def reset_token(self, request: request.Request, id: str, **kwargs) -> response.Response:
        team = self.get_object()
        team.reset_token_and_save(user=request.user, is_impersonated_session=is_impersonated_session(request))
        return response.Response(TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(
        methods=["PATCH"],
        detail=True,
        # Only ADMIN or higher users are allowed to access this project
        permission_classes=[TeamMemberStrictManagementPermission],
    )
    def rotate_secret_token(self, request: request.Request, id: str, **kwargs) -> response.Response:
        team = self.get_object()
        team.rotate_secret_token_and_save(user=request.user, is_impersonated_session=is_impersonated_session(request))
        return response.Response(TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(
        methods=["PATCH"],
        detail=True,
        # Only ADMIN or higher users are allowed to access this project
        permission_classes=[TeamMemberStrictManagementPermission],
    )
    def delete_secret_token_backup(self, request: request.Request, id: str, **kwargs) -> response.Response:
        team = self.get_object()
        team.delete_secret_token_backup_and_save(
            user=request.user, is_impersonated_session=is_impersonated_session(request)
        )
        return response.Response(TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(
        methods=["GET", "POST", "DELETE"],
        detail=True,
        permission_classes=[IsAuthenticated],
    )
    def default_evaluation_tags(self, request: request.Request, id: str, **kwargs) -> response.Response:
        """Manage default evaluation tags for a team"""
        team = self.get_object()

        if request.method == "GET":
            # Return list of default evaluation tags
            default_tags = TeamDefaultEvaluationTag.objects.filter(team=team).select_related("tag")
            tags_data = [{"id": dt.id, "name": dt.tag.name} for dt in default_tags]
            return response.Response(
                {"default_evaluation_tags": tags_data, "enabled": team.default_evaluation_environments_enabled}
            )

        elif request.method == "POST":
            # Add a default evaluation tag
            tag_name = request.data.get("tag_name", "").strip().lower()
            if not tag_name:
                return response.Response({"error": "tag_name is required"}, status=400)

            with transaction.atomic():
                # Select and lock all existing tags for this team
                existing_tags = list(TeamDefaultEvaluationTag.objects.filter(team=team).select_for_update())
                if len(existing_tags) >= 10:
                    return response.Response({"error": "Maximum of 10 default evaluation tags allowed"}, status=400)

                tag, _ = Tag.objects.get_or_create(name=tag_name, team=team)
                default_tag, created = TeamDefaultEvaluationTag.objects.get_or_create(team=team, tag=tag)

                if created:
                    report_user_action(
                        cast(User, request.user),
                        "default evaluation tag added",
                        {"team_id": team.id, "tag_name": tag_name},
                    )

            return response.Response({"id": default_tag.id, "name": tag.name, "created": created})

        else:  # DELETE
            # Remove a default evaluation tag
            # Handle both request.data and query params for DELETE (test client compatibility)
            tag_name = request.data.get("tag_name", "") or request.GET.get("tag_name", "")
            tag_name = tag_name.strip().lower()
            if not tag_name:
                return response.Response({"error": "tag_name is required"}, status=400)

            with transaction.atomic():
                try:
                    tag = Tag.objects.get(name=tag_name, team=team)
                    deleted_count, _ = TeamDefaultEvaluationTag.objects.filter(team=team, tag=tag).delete()

                    if deleted_count > 0:
                        report_user_action(
                            cast(User, request.user),
                            "default evaluation tag removed",
                            {"team_id": team.id, "tag_name": tag_name},
                        )

                    return response.Response({"success": True})
                except Tag.DoesNotExist:
                    return response.Response({"error": "Tag not found"}, status=404)

    @action(
        methods=["GET"],
        detail=True,
        permission_classes=[IsAuthenticated],
    )
    def is_generating_demo_data(self, request: request.Request, id: str, **kwargs) -> response.Response:
        team = self.get_object()
        return response.Response({"is_generating_demo_data": team.get_is_generating_demo_data()})

    @action(methods=["GET"], detail=True)
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        team = self.get_object()

        activity_page = load_activity(
            scope="Team",
            team_id=team.pk,
            item_ids=[str(team.pk)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)

    @action(
        methods=["PATCH"],
        detail=True,
        required_scopes=["project:read"],
    )
    def add_product_intent(self, request: request.Request, *args, **kwargs):
        team = self.get_object()
        user = request.user
        current_url = request.headers.get("Referer")
        session_id = request.headers.get("X-Posthog-Session-Id")

        serializer = ProductIntentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ProductIntent.register(
            team=team,
            product_type=serializer.validated_data["product_type"],
            context=serializer.validated_data["intent_context"],
            user=cast(User, user),
            metadata={**serializer.validated_data["metadata"], "$current_url": current_url, "$session_id": session_id},
        )

        return response.Response(TeamSerializer(team, context=self.get_serializer_context()).data, status=201)

    @action(
        methods=["PATCH"],
        detail=True,
        required_scopes=["project:read"],
    )
    def complete_product_onboarding(self, request: request.Request, *args, **kwargs):
        team = self.get_object()
        product_type = request.data.get("product_type")
        user = request.user
        current_url = request.headers.get("Referer")
        session_id = request.headers.get("X-Posthog-Session-Id")

        if not product_type:
            return response.Response({"error": "product_type is required"}, status=400)

        product_intent_serializer = ProductIntentSerializer(data=request.data)
        product_intent_serializer.is_valid(raise_exception=True)
        intent_data = product_intent_serializer.validated_data
        product_intent = ProductIntent.register(
            team=team,
            product_type=product_type,
            context=intent_data["intent_context"],
            user=cast(User, user),
            metadata={**intent_data["metadata"], "$current_url": current_url, "$session_id": session_id},
            is_onboarding=True,
        )

        if isinstance(user, User):  # typing
            report_user_action(
                user,
                "product onboarding completed",
                {
                    "product_key": product_type,
                    "$current_url": current_url,
                    "$session_id": session_id,
                    "intent_context": intent_data["intent_context"],
                    "intent_created_at": product_intent.created_at,
                    "intent_updated_at": product_intent.updated_at,
                    "realm": get_instance_realm(),
                },
                team=team,
            )

        return response.Response(TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(methods=["GET"], detail=True, required_scopes=["project:read"], url_path="event_ingestion_restrictions")
    def event_ingestion_restrictions(self, request, **kwargs):
        team = self.get_object()
        restrictions = EventIngestionRestrictionConfig.objects.filter(token=team.api_token)
        data = [
            {
                "restriction_type": restriction.restriction_type,
                "distinct_ids": restriction.distinct_ids,
            }
            for restriction in restrictions
        ]
        return response.Response(data)

    @cached_property
    def user_permissions(self):
        team = self.get_object() if self.action in actions_that_require_current_team else None
        return UserPermissions(cast(User, self.request.user), team)


class RootTeamViewSet(TeamViewSet):
    # NOTE: We don't want people creating environments via the "current_organization"/"current_project" concept, but
    # rather specify the org ID and project ID in the URL - hence this is hidden from the API docs, but used in the app
    hide_api_docs = True


def validate_team_attrs(
    attrs: dict[str, Any], view: TeamAndOrgViewSetMixin, request: request.Request, instance: Optional[Team | Project]
) -> dict[str, Any]:
    if "primary_dashboard" in attrs:
        if not instance:
            raise exceptions.ValidationError(
                {"primary_dashboard": "Primary dashboard cannot be set on project creation."}
            )
        if attrs["primary_dashboard"] and attrs["primary_dashboard"].team_id != instance.id:
            raise exceptions.ValidationError({"primary_dashboard": "Dashboard does not belong to this team."})

    if "autocapture_exceptions_errors_to_ignore" in attrs:
        if not isinstance(attrs["autocapture_exceptions_errors_to_ignore"], list):
            raise exceptions.ValidationError("Must provide a list for field: autocapture_exceptions_errors_to_ignore.")
        for error in attrs["autocapture_exceptions_errors_to_ignore"]:
            if not isinstance(error, str):
                raise exceptions.ValidationError(
                    "Must provide a list of strings to field: autocapture_exceptions_errors_to_ignore."
                )

        if len(json.dumps(attrs["autocapture_exceptions_errors_to_ignore"])) > 300:
            raise exceptions.ValidationError(
                "Field autocapture_exceptions_errors_to_ignore must be less than 300 characters. Complex config should be provided in posthog-js initialization."
            )
    return attrs


class PremiumMultiEnvironmentPermission(BasePermission):
    """Require user to have all necessary premium features on their plan for create access to the endpoint."""

    message = "You have reached the maximum limit of allowed environments for your current plan. Upgrade your plan to be able to create and manage more environments."

    def has_permission(self, request: request.Request, view) -> bool:
        if view.action not in CREATE_ACTIONS:
            return True

        try:
            project = view.project
        except KeyError:  # KeyError occurs when "project_id" is not in parents_query_dict
            raise exceptions.ValidationError(
                "Environments must be created under a specific project. Send the POST request to /api/projects/<project_id>/environments/ instead."
            )

        if request.data.get("is_demo"):
            # If we're requesting to make a demo project but the org already has a demo project
            if project.organization.teams.filter(is_demo=True).count() > 0:
                return False

        environments_feature = project.organization.get_available_feature(AvailableFeature.ENVIRONMENTS)
        current_non_demo_team_count = project.teams.exclude(is_demo=True).count()
        if environments_feature:
            allowed_team_per_project_count = environments_feature.get("limit")
            # If allowed_project_count is None then the user is allowed unlimited projects
            if allowed_team_per_project_count is None:
                return True
            # Check current limit against allowed limit
            if current_non_demo_team_count >= allowed_team_per_project_count:
                return False
        else:
            # If the org doesn't have the feature, they can only have one non-demo project
            if current_non_demo_team_count >= 1:
                return False

        # in any other case, we're good to go
        return True
