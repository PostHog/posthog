"""The main serializer for project settings."""

import re
from datetime import timedelta
from typing import Any, Literal, cast

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from drf_spectacular.utils import extend_schema_field
from opentelemetry import trace
from rest_framework import exceptions, serializers

from posthog.schema import HogQLQueryModifiers

from posthog.api.utils import validate_authorized_url_wildcards
from posthog.constants import LOGS_RETENTION_FEATURES_BY_DAYS, AvailableFeature
from posthog.geoip import get_geoip_properties
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Detail, dict_changes_between, log_activity
from posthog.models.group_type_mapping import cached_group_types_for_team
from posthog.models.organization import OrganizationMembership
from posthog.models.product_intent.product_intent import (
    cached_product_intents_for_team,
    enqueue_product_activation_calc_debounced,
)
from posthog.models.team.event_retention import should_enforce_events_retention
from posthog.models.team.setup_tasks import SetupTaskId
from posthog.models.team.team import CURRENCY_CODE_CHOICES, DEFAULT_CURRENCY
from posthog.models.team.team_caching import set_team_in_cache
from posthog.models.utils import UUIDT
from posthog.session_recordings.data_retention import (
    VALID_RETENTION_PERIODS,
    parse_feature_to_entitlement,
    retention_violates_entitlement,
    validate_retention_period,
)
from posthog.user_permissions import UserPermissionsSerializerMixin
from posthog.utils import get_instance_region, get_ip_address, get_week_start_for_country_code

from products.access_control.backend.presentation.access_control import UserAccessControlSerializerMixin
from products.web_analytics.backend.hogql_queries.custom_bot_definitions import (
    MAX_CUSTOM_BOT_DEFINITIONS,
    assert_patterns_compile as assert_custom_bot_patterns_compile,
    compiled_patterns as compiled_custom_bot_patterns,
    parse_rules as parse_custom_bot_rules,
    validate_rule as validate_custom_bot_rule,
    validate_rule_set as validate_custom_bot_rule_set,
)

from . import conversations_settings, live_events, marketing_config, settings_validation, team_config

tracer = trace.get_tracer(__name__)


class TeamSerializer(serializers.ModelSerializer, UserPermissionsSerializerMixin, UserAccessControlSerializerMixin):
    instance: Team | None
    _group_types_cache: list[dict[str, Any]] | None = None

    effective_membership_level = serializers.SerializerMethodField()
    has_group_types = serializers.SerializerMethodField()
    group_types = serializers.SerializerMethodField()
    live_events_token = serializers.SerializerMethodField()
    product_intents = serializers.SerializerMethodField()
    managed_viewsets = serializers.SerializerMethodField()
    available_setup_task_ids = serializers.SerializerMethodField()
    revenue_analytics_config = team_config.TeamRevenueAnalyticsConfigSerializer(required=False)
    marketing_analytics_config = marketing_config.TeamMarketingAnalyticsConfigSerializer(required=False)
    customer_analytics_config = team_config.TeamCustomerAnalyticsConfigSerializer(required=False)
    workflows_config = team_config.TeamWorkflowsConfigSerializer(required=False)
    feature_flag_policy_config = team_config.TeamFeatureFlagPolicyConfigSerializer(required=False)
    base_currency = serializers.ChoiceField(choices=CURRENCY_CODE_CHOICES, default=DEFAULT_CURRENCY)
    event_retention_months = serializers.IntegerField(
        read_only=True,
        help_text=(
            "The team's events data retention window in months (plan-derived, synced from billing). When retention "
            "enforcement is active for the team, queries do not return events older than this many months. "
            "Read-only: this value follows your plan's data retention entitlement, so neither you nor PostHog "
            "support can change it unless your organization is on the enterprise plan. Background and discussion: "
            "https://github.com/PostHog/posthog/issues/17031"
        ),
    )
    events_retention_enforced = serializers.SerializerMethodField(
        help_text=(
            "Whether events data retention is currently enforced for this team (cohort/flag gated). Read-only: "
            "neither you nor PostHog support can turn enforcement off, and the retention window itself only "
            "changes with your plan. Background and discussion: https://github.com/PostHog/posthog/issues/17031"
        )
    )

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
            *team_config.TEAM_CONFIG_FIELDS,
            # Computed fields
            "effective_membership_level",
            "has_group_types",
            "group_types",
            "live_events_token",
            "product_intents",
            "managed_viewsets",
            "available_setup_task_ids",
            "event_retention_months",
            "events_retention_enforced",
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
            "available_setup_task_ids",
        )

    def to_representation(self, instance):
        with tracer.start_as_current_span("team_serializer.default_fields"):
            representation = super().to_representation(instance)
        # fallback to the default posthog data theme id, if the color feature isn't available e.g. after a downgrade
        if not instance.organization.is_feature_available(AvailableFeature.DATA_COLOR_THEMES):
            with tracer.start_as_current_span("team_serializer.default_data_theme_fallback"):
                representation["default_data_theme"] = live_events._default_data_color_theme_id()

        return representation

    @tracer.start_as_current_span("team_serializer.effective_membership_level")
    def get_effective_membership_level(self, team: Team) -> OrganizationMembership.Level | None:
        # TODO: Map from user_access_controls
        return self.user_permissions.team(team).effective_membership_level

    @tracer.start_as_current_span("team_serializer.has_group_types")
    def get_has_group_types(self, team: Team) -> bool:
        return bool(self._get_group_types(team))

    @tracer.start_as_current_span("team_serializer.group_types")
    def get_group_types(self, team: Team) -> list[dict[str, Any]]:
        return self._get_group_types(team)

    def _get_group_types(self, team: Team) -> list[dict[str, Any]]:
        group_types = self._group_types_cache
        if group_types is None:
            group_types = cached_group_types_for_team(team)
            self._group_types_cache = group_types
        return group_types

    @extend_schema_field(serializers.BooleanField())
    @tracer.start_as_current_span("team_serializer.events_retention_enforced")
    def get_events_retention_enforced(self, team: Team) -> bool:
        return should_enforce_events_retention(team.id)

    @tracer.start_as_current_span("team_serializer.live_events_token")
    def get_live_events_token(self, team: Team) -> str | None:
        request = self.context.get("request")
        user_id = request.user.id if request and hasattr(request, "user") and request.user.is_authenticated else None
        return live_events.get_or_mint_live_events_token(team, user_id)

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    @tracer.start_as_current_span("team_serializer.product_intents")
    def get_product_intents(self, obj):
        # Debounce-then-enqueue rather than .delay() on every render. The helper
        # checks a cache key first and skips the broker round-trip entirely if
        # we've already enqueued for this team in the last 24h. 99% of renders
        # become a cache hit; the remaining ones still enqueue exactly as before.
        enqueue_product_activation_calc_debounced(obj.id)
        return cached_product_intents_for_team(obj.id)

    @extend_schema_field(serializers.DictField(child=serializers.BooleanField()))
    @tracer.start_as_current_span("team_serializer.managed_viewsets")
    def get_managed_viewsets(self, obj):
        from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
        from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

        enabled_viewsets = DataWarehouseManagedViewSet.objects.filter(team=obj).values_list("kind", flat=True)
        enabled_set = set(enabled_viewsets)

        return {kind: (kind in enabled_set) for kind, _ in DataWarehouseManagedViewSetKind.choices}

    @extend_schema_field(
        serializers.ListField(child=serializers.ChoiceField(choices=[(e.value, e.value) for e in SetupTaskId]))
    )
    def get_available_setup_task_ids(self, obj) -> list[str]:
        return [e.value for e in SetupTaskId]

    @staticmethod
    def validate_test_account_filters(value: object) -> list[dict[str, object]]:
        return settings_validation.validate_test_account_filters(value)

    @staticmethod
    def validate_path_cleaning_filters(value: object) -> object:
        return settings_validation.validate_path_cleaning_filters(value)

    @staticmethod
    def validate_revenue_analytics_config(value):
        if value is None:
            return None

        if not isinstance(value, dict):
            raise exceptions.ValidationError("Must provide a dictionary or None.")

        serializer = team_config.TeamRevenueAnalyticsConfigSerializer(data=value)
        if not serializer.is_valid():
            raise exceptions.ValidationError(settings_validation._format_serializer_errors(serializer.errors))

        return serializer.validated_data

    @staticmethod
    def validate_marketing_analytics_config(value):
        if value is None:
            return None

        serializer = marketing_config.TeamMarketingAnalyticsConfigSerializer(data=value)
        if not serializer.is_valid():
            raise exceptions.ValidationError(settings_validation._format_serializer_errors(serializer.errors))
        return serializer.validated_data

    @staticmethod
    def validate_customer_analytics_config(value):
        if value is None:
            return None

        serializer = team_config.TeamCustomerAnalyticsConfigSerializer(data=value)
        if not serializer.is_valid():
            raise exceptions.ValidationError(settings_validation._format_serializer_errors(serializer.errors))
        return serializer.validated_data

    @staticmethod
    def validate_workflows_config(value):
        if value is None:
            return None

        serializer = team_config.TeamWorkflowsConfigSerializer(data=value)
        if not serializer.is_valid():
            raise exceptions.ValidationError(settings_validation._format_serializer_errors(serializer.errors))
        return serializer.validated_data

    @staticmethod
    def validate_feature_flag_policy_config(value):
        if value is None:
            return None

        serializer = team_config.TeamFeatureFlagPolicyConfigSerializer(data=value)
        if not serializer.is_valid():
            raise exceptions.ValidationError(settings_validation._format_serializer_errors(serializer.errors))
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

        # jsonb containment (`__contains={"id": <int>}`) is type-sensitive, so a non-integer id
        # makes the flag-delete guard miss this row and delete a flag the team still advertises.
        # A numeric string is normalized instead of rejected, so a client sending "123" stores a
        # usable row rather than a broken one. Bools and floats are excluded because
        # isinstance(True, int) is True, and int(12.5) would silently link flag 12.
        flag_id = value["id"]
        if isinstance(flag_id, bool) or not isinstance(flag_id, int | str):
            raise exceptions.ValidationError("Must provide an integer 'id'.")
        try:
            return {**value, "id": int(flag_id)}
        except ValueError:
            raise exceptions.ValidationError("Must provide an integer 'id'.")

    @staticmethod
    def validate_session_recording_trigger_match_type_config(value) -> Literal["all", "any"] | None:
        if value not in ["all", "any", None]:
            raise exceptions.ValidationError(
                "Must provide a valid trigger match type. Only 'all' or 'any' or None are allowed."
            )

        return value

    @staticmethod
    def validate_session_recording_trigger_groups(value) -> dict | None:
        """
        Validate V2 trigger groups configuration.

        Expected schema:
        {
            "version": 2,
            "groups": [
                {
                    "id": "string",
                    "name": "string" (optional),
                    "sampleRate": 0.0-1.0,
                    "minDurationMs": 0-30000 (optional),
                    "conditions": {
                        "matchType": "any" | "all",
                        "events": ["event1", ...] (optional),
                        "urls": [{"url": "regex", "matching": "regex"}] (optional),
                        "flag": "flag-key" | {"id": 1, "key": "flag-key", "variant": "test"} (optional, single flag)
                    }
                }
            ]
        }
        """
        if value is None:
            return None

        if not isinstance(value, dict):
            raise exceptions.ValidationError("Must provide a dictionary or None.")

        # Validate version
        if "version" not in value:
            raise exceptions.ValidationError("Missing required field: 'version'.")

        if value["version"] != 2:
            raise exceptions.ValidationError(f"Invalid version: {value['version']}. Only version 2 is supported.")

        # Validate groups array
        if "groups" not in value:
            raise exceptions.ValidationError("Missing required field: 'groups'.")

        if not isinstance(value["groups"], list):
            raise exceptions.ValidationError("Field 'groups' must be an array.")

        # Validate each group
        for idx, group in enumerate(value["groups"]):
            # Inline validation of each trigger group
            if not isinstance(group, dict):
                raise exceptions.ValidationError(f"Group {idx}: must be a dictionary.")

            # Required fields
            required_fields = ["id", "sampleRate", "conditions"]
            for field in required_fields:
                if field not in group:
                    raise exceptions.ValidationError(f"Group {idx}: missing required field '{field}'.")

            # Validate sampleRate
            rate = group["sampleRate"]
            if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not (0 <= rate <= 1):
                raise exceptions.ValidationError(
                    f"Group {idx}: invalid sampleRate '{rate}'. Must be a number between 0 and 1."
                )

            # Validate minDurationMs if present
            if "minDurationMs" in group:
                min_duration = group["minDurationMs"]
                if isinstance(min_duration, bool) or not isinstance(min_duration, int):
                    raise exceptions.ValidationError(
                        f"Group {idx}: 'minDurationMs' must be an integer, got {type(min_duration).__name__}."
                    )
                if min_duration < 0 or min_duration > 30000:
                    raise exceptions.ValidationError(
                        f"Group {idx}: 'minDurationMs' must be between 0 and 30000 (30 seconds). Got: {min_duration}."
                    )

            # Validate conditions
            conditions = group["conditions"]
            if not isinstance(conditions, dict):
                raise exceptions.ValidationError(f"Group {idx}: field 'conditions' must be a dictionary.")

            # Validate matchType
            if "matchType" in conditions:
                if conditions["matchType"] not in ["any", "all"]:
                    raise exceptions.ValidationError(
                        f"Group {idx}: invalid matchType '{conditions['matchType']}'. Must be 'any' or 'all'."
                    )

            # Validate events array if present
            if "events" in conditions:
                if not isinstance(conditions["events"], list):
                    raise exceptions.ValidationError(f"Group {idx}: field 'events' must be an array.")
                for event_idx, event in enumerate(conditions["events"]):
                    if isinstance(event, str):
                        pass  # Simple event name is valid
                    elif isinstance(event, dict):
                        if "name" not in event or not isinstance(event["name"], str):
                            raise exceptions.ValidationError(
                                f"Group {idx}: event {event_idx} object must have a string 'name' field."
                            )
                        if "properties" in event:
                            settings_validation._validate_trigger_property_filters(
                                event["properties"], f"Group {idx}, event '{event['name']}'"
                            )
                    else:
                        raise exceptions.ValidationError(
                            f"Group {idx}: event {event_idx} must be a string or object with 'name'."
                        )

            # Validate URLs array if present
            if "urls" in conditions:
                if not isinstance(conditions["urls"], list):
                    raise exceptions.ValidationError(f"Group {idx}: field 'urls' must be an array.")
                for url_config in conditions["urls"]:
                    if not isinstance(url_config, dict):
                        raise exceptions.ValidationError(f"Group {idx}: URL config must be a dictionary.")
                    if "url" not in url_config or "matching" not in url_config:
                        raise exceptions.ValidationError(
                            f"Group {idx}: URL config must have 'url' and 'matching' fields."
                        )
                    if url_config["matching"] != "regex":
                        raise exceptions.ValidationError(
                            f"Group {idx}: URL matching must be 'regex'. Got: '{url_config['matching']}'."
                        )
                    # Validate regex pattern
                    try:
                        re.compile(url_config["url"])
                    except re.error:
                        raise exceptions.ValidationError(
                            f"Group {idx}: invalid regex pattern in URL: '{url_config['url']}'."
                        )

            # Validate flag (single) if present
            if "flag" in conditions:
                flag_config = conditions["flag"]
                if isinstance(flag_config, str):
                    pass  # Simple flag key is valid
                elif isinstance(flag_config, dict):
                    # LinkedFeatureFlag object with id, key, and optional variant
                    if "key" not in flag_config:
                        raise exceptions.ValidationError(f"Group {idx}: flag object must have 'key' field.")
                    if not isinstance(flag_config["key"], str):
                        raise exceptions.ValidationError(f"Group {idx}: flag 'key' must be a string.")
                    # id and variant are optional
                elif flag_config is not None:
                    raise exceptions.ValidationError(
                        f"Group {idx}: 'flag' must be a string (flag key), object (LinkedFeatureFlag), or null."
                    )

            # Validate group-level property filters (shared WHERE clause for all triggers in group)
            if "properties" in conditions:
                settings_validation._validate_trigger_property_filters(conditions["properties"], f"Group {idx}")

        # Note: All matching groups are evaluated independently
        # If any group's sample rate hits, the session is recorded (union behavior)

        # Validate fallback sample rate if present
        if "fallbackSampleRate" in value:
            rate = value["fallbackSampleRate"]
            if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not (0 <= rate <= 1):
                raise exceptions.ValidationError(
                    f"Invalid fallbackSampleRate: {rate}. Must be a number between 0 and 1."
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
        urls = [url for url in value if url]
        validate_authorized_url_wildcards(urls)
        return urls

    def validate_recording_domains(self, value: list[str | None] | None) -> list[str] | None:
        if value is None:
            return value
        return [domain for domain in value if domain]

    def validate_conversations_settings(self, value: dict | None) -> dict | None:
        if value is None:
            return value
        # Filter out None values from widget_domains if present
        if "widget_domains" in value and value["widget_domains"] is not None:
            value["widget_domains"] = [domain for domain in value["widget_domains"] if domain]
            validate_authorized_url_wildcards(value["widget_domains"])
        # Strip widget_public_token from user input - it's auto-generated only
        if "widget_public_token" in value:
            value.pop("widget_public_token")
        # Integration state is managed only by dedicated endpoints, not user input
        for managed_key in (
            "slack_bot_token",
            "slack_team_id",
            "slack_enabled",
            "slack_scopes",
            "email_enabled",
            "teams_enabled",
            "teams_tenant_id",
            "teams_team_id",
            "teams_team_name",
            "teams_channel_id",
            "teams_channel_name",
            "teams_channels",
        ):
            value.pop(managed_key, None)
        # Normalize multi-channel list: must be a list of non-empty strings, deduped, capped at 50
        if "slack_channel_ids" in value:
            raw = value.get("slack_channel_ids")
            if isinstance(raw, list):
                cleaned: list[str] = []
                seen: set[str] = set()
                for item in raw:
                    if isinstance(item, str) and item and item not in seen:
                        seen.add(item)
                        cleaned.append(item)
                value["slack_channel_ids"] = cleaned[:50]
            else:
                value.pop("slack_channel_ids", None)
        icon_url = value.get("slack_bot_icon_url")
        if icon_url is not None:
            if not isinstance(icon_url, str):
                raise serializers.ValidationError({"slack_bot_icon_url": "Must be a string."})
            icon_url = icon_url.strip()
            value["slack_bot_icon_url"] = icon_url or None
            if icon_url and not icon_url.startswith("https://"):
                raise serializers.ValidationError({"slack_bot_icon_url": "Must be an HTTPS URL."})
        display_name = value.get("slack_bot_display_name")
        if display_name is not None:
            if not isinstance(display_name, str):
                raise serializers.ValidationError({"slack_bot_display_name": "Must be a string."})
            display_name = display_name.strip()
            value["slack_bot_display_name"] = display_name or None
            if display_name and (len(display_name) > 200 or any(ord(c) < 32 for c in display_name)):
                raise serializers.ValidationError(
                    {"slack_bot_display_name": "Must be 200 characters or fewer with no control characters."}
                )
        for toggle_key in ("slack_notify_on_join", "slack_notify_on_leave", "slack_nudge_enabled"):
            if toggle_key in value:
                value[toggle_key] = bool(value[toggle_key])
        if "slack_alert_channel_id" in value:
            alert_channel = value.get("slack_alert_channel_id")
            if alert_channel is None:
                value["slack_alert_channel_id"] = None
            elif isinstance(alert_channel, str):
                value["slack_alert_channel_id"] = alert_channel.strip() or None
            else:
                raise serializers.ValidationError({"slack_alert_channel_id": "Must be a string."})
        # AI resolution channels: list of valid channel strings or null
        VALID_CHANNELS = {"widget", "email", "slack", "teams", "github"}
        if "ai_resolution_channels" in value:
            channels = value.get("ai_resolution_channels")
            if channels is None:
                pass
            elif isinstance(channels, list):
                invalid = [c for c in channels if not isinstance(c, str) or c not in VALID_CHANNELS]
                if invalid:
                    raise serializers.ValidationError(
                        {
                            "ai_resolution_channels": f"Invalid channel(s): {', '.join(str(c) for c in invalid)}. "
                            f"Valid options: {', '.join(sorted(VALID_CHANNELS))}."
                        }
                    )
                value["ai_resolution_channels"] = channels
            else:
                raise serializers.ValidationError(
                    {"ai_resolution_channels": "Must be a list of channel names or null."}
                )
        # AI reply modes: { channel: { ticket_type: mode } } or null
        VALID_REPLY_MODES = {"private_note", "bot_reply"}
        VALID_TICKET_TYPES = {"how_to", "diagnostic", "account_billing"}
        # Only how_to replies may be published to the ticket author. diagnostic/account_billing
        # draw on project data (events, persons, recordings, logs) and must stay private notes —
        # there's no per-author authorization that the customer is entitled to that data.
        BOT_REPLY_TICKET_TYPES = {"how_to"}
        if "ai_reply_modes" in value:
            modes = value.get("ai_reply_modes")
            if modes is None:
                pass
            elif isinstance(modes, dict):
                cleaned_modes: dict[str, dict[str, str]] = {}
                for ch, type_map in modes.items():
                    if ch not in VALID_CHANNELS or not isinstance(type_map, dict):
                        continue
                    cleaned_map: dict[str, str] = {}
                    for tt, mode in type_map.items():
                        if tt not in VALID_TICKET_TYPES or mode not in VALID_REPLY_MODES:
                            continue
                        # Demote bot_reply to private_note for ticket types that may never be
                        # published (diagnostic/account_billing). Coerce rather than reject so a
                        # stale value doesn't block unrelated settings saves.
                        if mode == "bot_reply" and tt not in BOT_REPLY_TICKET_TYPES:
                            mode = "private_note"
                        cleaned_map[tt] = mode
                    if cleaned_map:
                        cleaned_modes[ch] = cleaned_map
                value["ai_reply_modes"] = cleaned_modes
            else:
                raise serializers.ValidationError({"ai_reply_modes": "Must be an object or null."})
        return value

    def validate_receive_org_level_activity_logs(self, value: bool | None) -> bool | None:
        if value is None:
            return value

        request = self.context.get("request")
        if not request:
            return value

        user = request.user

        if self.instance:
            try:
                membership = OrganizationMembership.objects.get(user=user, organization=self.instance.organization)
                if membership.level < OrganizationMembership.Level.ADMIN:
                    raise exceptions.PermissionDenied(
                        "Only organization owners and admins can modify the receive_org_level_activity_logs setting."
                    )
            except OrganizationMembership.DoesNotExist:
                raise exceptions.PermissionDenied("You must be a member of this organization.")

        return value

    VALID_RETENTION_DAYS = {14, 30}

    def validate_logs_settings(self, value: dict | None) -> dict | None:
        if value is None:
            return value

        new_retention = value.get("retention_days")
        if new_retention is not None and new_retention not in TeamSerializer.VALID_RETENTION_DAYS:
            raise exceptions.ValidationError(
                f"retention_days must be one of {sorted(TeamSerializer.VALID_RETENTION_DAYS)}"
            )

        team = (
            self.instance.passthrough_team
            if self.instance is not None and hasattr(self.instance, "passthrough_team")
            else self.instance
        )
        logs_settings = team.logs_settings if team is not None else None
        old_retention = logs_settings.get("retention_days") if logs_settings else None

        if new_retention is not None and old_retention != new_retention:
            required_feature = LOGS_RETENTION_FEATURES_BY_DAYS.get(new_retention)
            if required_feature:
                organization = settings_validation._get_organization_for_logs_settings_check(self)
                if organization is None or not organization.is_feature_available(required_feature):
                    raise exceptions.PermissionDenied(
                        f"This organization does not have permission to set Logs retention to {new_retention} days."
                    )

        # Only validate retention throttling if we have an existing retention setting
        if self.instance and logs_settings:
            old_last_updated = logs_settings.get("retention_last_updated")

            # Check if retention_days is being changed
            if new_retention is not None and old_retention != new_retention:
                value["retention_last_updated"] = timezone.now().isoformat()
                # Check if retention_last_updated exists and is within 24 hours
                if old_last_updated:
                    last_updated = parse_datetime(old_last_updated)
                    if last_updated:
                        time_since_update = timezone.now() - last_updated
                        if time_since_update < timedelta(hours=24):
                            hours_remaining = 24 - (time_since_update.total_seconds() / 3600)
                            raise exceptions.ValidationError(
                                f"You can only update retention settings once per 24 hours. "
                                f"Please wait {int(hours_remaining)} more hour(s)."
                            )

        return value

    @staticmethod
    def validate_modifiers(value: dict | None) -> dict | None:
        if value is None:
            return value

        if not isinstance(value, dict):
            raise exceptions.ValidationError("Must provide a dictionary or None.")

        if "bounceRateDurationSeconds" in value:
            bounce_rate = value["bounceRateDurationSeconds"]
            if bounce_rate is not None:
                if not isinstance(bounce_rate, (int, float)):
                    raise exceptions.ValidationError({"bounceRateDurationSeconds": "Must be a number."})
                if bounce_rate < 1 or bounce_rate > 120:
                    raise exceptions.ValidationError(
                        {"bounceRateDurationSeconds": "Must be between 1 and 120 seconds."}
                    )

        if "customBotDefinitions" in value and isinstance(value["customBotDefinitions"], list):
            # Cap before parsing, so an oversized list is rejected without instantiating a model
            # per entry.
            if len(value["customBotDefinitions"]) > MAX_CUSTOM_BOT_DEFINITIONS:
                raise exceptions.ValidationError(
                    {"customBotDefinitions": f"You can define at most {MAX_CUSTOM_BOT_DEFINITIONS} bots."}
                )
            # Strict, so a malformed rule is rejected with a specific error rather than the
            # generic "Invalid modifier key.", and the stored list is normalized.
            try:
                parsed = parse_custom_bot_rules(value["customBotDefinitions"], strict=True)
            except ValueError as error:
                raise exceptions.ValidationError({"customBotDefinitions": str(error)})
            value = {**value, "customBotDefinitions": [rule.model_dump(exclude_none=True) for rule in parsed]}

        try:
            modifiers = HogQLQueryModifiers(**value)
        except Exception:
            raise exceptions.ValidationError(f"Invalid modifier key.")

        if "customBotDefinitions" in value:
            rules = modifiers.customBotDefinitions or []
            if len(rules) > MAX_CUSTOM_BOT_DEFINITIONS:
                raise exceptions.ValidationError(
                    {"customBotDefinitions": f"You can define at most {MAX_CUSTOM_BOT_DEFINITIONS} bots."}
                )
            for rule in rules:
                # An unusable pattern would break every query that reads $virt_is_bot for this
                # project, so it is rejected here rather than dropped silently at query time.
                try:
                    validate_custom_bot_rule(rule)
                except ValueError as error:
                    # An empty name would render as an orphaned leading colon.
                    message = f"{rule.name}: {error}" if rule.name else str(error)
                    raise exceptions.ValidationError({"customBotDefinitions": message})
            try:
                validate_custom_bot_rule_set(rules)
                assert_custom_bot_patterns_compile(compiled_custom_bot_patterns(rules))
            except ValueError as error:
                raise exceptions.ValidationError({"customBotDefinitions": str(error)})

        return value

    def validate_proactive_tasks_enabled(self, value: bool | None) -> bool | None:
        if not value or settings.DEBUG:
            return value

        # Only team ID 2 in US region can enable proactive tasks
        if self.instance and self.instance.id == 2 and get_instance_region() == "US":
            return value

        raise exceptions.PermissionDenied("Proactive tasks can only be enabled for authorized teams.")

    def validate(self, attrs: Any) -> Any:
        attrs = settings_validation.validate_team_attrs(attrs, self.context["view"], self.instance)
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
            was_impersonated=is_impersonated(request),
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

        if config_data := validated_data.pop("customer_analytics_config", None):
            self._update_customer_analytics_config(instance, config_data)

        if config_data := validated_data.pop("workflows_config", None):
            self._update_workflows_config(instance, config_data)

        if config_data := validated_data.pop("feature_flag_policy_config", None):
            self._update_feature_flag_policy_config(instance, config_data)

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
                    was_impersonated=is_impersonated(self.context["request"]),
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

        # Merge conversations_settings with existing values, unless explicitly clearing with null
        if "conversations_settings" in validated_data and validated_data["conversations_settings"] is not None:
            existing_settings = instance.conversations_settings or {}
            new_settings = validated_data["conversations_settings"]
            validated_data["conversations_settings"] = {**existing_settings, **new_settings}

        validated_data = conversations_settings.handle_conversations_token_on_update(
            validated_data, instance.conversations_enabled, instance.conversations_settings
        )

        # Merge modifiers with existing values so that updating one modifier doesn't wipe out others
        if "modifiers" in validated_data and validated_data["modifiers"] is not None:
            validated_data["modifiers"] = {
                **(instance.modifiers or {}),
                **validated_data["modifiers"],
            }

        # Persist only the fields this request changes. A full-row save() writes back every
        # column from this request's snapshot of the team, so two concurrent PATCHes clobber
        # each other — e.g. an `onboarding_tasks` PATCH racing the onboarding-completion PATCH
        # erased `has_completed_onboarding_for` and reverted `completed_snippet_onboarding`,
        # bouncing freshly onboarded users back into onboarding.
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if validated_data:
            # auto_now fields only refresh when included in update_fields
            instance.save(update_fields=[*validated_data.keys(), "updated_at"])
        # Snapshot before the cache refresh below so the audit diff only reflects this
        # request's writes, not fields a concurrent request changed.
        after_update = instance.__dict__.copy()
        if validated_data:
            # The in-memory instance may hold stale values for fields a concurrent request
            # changed, and the post-save receiver has already cached that snapshot. Reload
            # and re-cache so the team cache reflects the merged row.
            instance.refresh_from_db()
            set_team_in_cache(instance.api_token, instance)
        updated_team = instance

        changes = dict_changes_between("Team", before_update, after_update, use_field_exclusions=True)

        log_activity(
            organization_id=cast(UUIDT, instance.organization_id),
            team_id=instance.pk,
            user=cast(User, self.context["request"].user),
            was_impersonated=is_impersonated(self.context["request"]),
            scope="Team",
            item_id=instance.pk,
            activity="updated",
            detail=Detail(
                name=str(instance.name),
                changes=changes,
            ),
        )

        conversations_settings.report_conversations_settings_changes(
            cast(User, self.context["request"].user),
            before_update.get("conversations_settings"),
            updated_team,
        )

        return updated_team

    def _update_revenue_analytics_config(self, instance: Team, validated_data: dict[str, Any]) -> Team:
        # Capture old config before saving
        old_config = {
            "events": [event.model_dump() for event in (instance.revenue_analytics_config.events or [])],
            "filter_test_accounts": instance.revenue_analytics_config.filter_test_accounts,
        }

        serializer = team_config.TeamRevenueAnalyticsConfigSerializer(
            instance.revenue_analytics_config,
            data=validated_data,
            partial=True,
            context={**self.context, "user_access_control": self.user_access_control},
        )
        if not serializer.is_valid():
            raise serializers.ValidationError(settings_validation._format_serializer_errors(serializer.errors))

        serializer.save()

        # Log activity for revenue analytics config changes
        new_config = {
            "events": validated_data.get("events", []),
            "filter_test_accounts": validated_data.get("filter_test_accounts", False),
        }

        self._capture_diff(instance, "revenue_analytics_config", old_config, new_config)

        if "events" in validated_data:
            from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
            from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

            managed_viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
                team=instance,
                kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
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
            "filter_test_accounts": instance.marketing_analytics_config.filter_test_accounts,
            # Add other fields as they're added to the model
            # "conversion_goals": instance.marketing_analytics_config.conversion_goals.copy() if instance.marketing_analytics_config.conversion_goals else [],
        }

        marketing_serializer = marketing_config.TeamMarketingAnalyticsConfigSerializer(
            instance.marketing_analytics_config,
            data=validated_data,
            partial=True,
            context={**self.context, "user_access_control": self.user_access_control},
        )
        if not marketing_serializer.is_valid():
            raise serializers.ValidationError(
                settings_validation._format_serializer_errors(marketing_serializer.errors)
            )

        marketing_serializer.save()

        # Log activity for marketing analytics config changes
        new_config = {
            "sources_map": validated_data.get("sources_map", {}),
            "attribution_window_days": validated_data.get("attribution_window_days"),
            "attribution_mode": validated_data.get("attribution_mode"),
            "filter_test_accounts": validated_data.get("filter_test_accounts"),
            # Add other fields as they're added to the model
            # "conversion_goals": validated_data.get("conversion_goals", []),
        }

        self._capture_diff(instance, "marketing_analytics_config", old_config, new_config)
        return instance

    def _update_customer_analytics_config(self, instance: Team, validated_data: dict[str, Any]) -> Team:
        old_config = {
            "activity_event": instance.customer_analytics_config.activity_event,
            "signup_pageview_event": instance.customer_analytics_config.signup_pageview_event,
            "signup_event": instance.customer_analytics_config.signup_event,
            "subscription_event": instance.customer_analytics_config.subscription_event,
            "payment_event": instance.customer_analytics_config.payment_event,
            "account_group_type_index": instance.customer_analytics_config.account_group_type_index,
        }

        serializer = team_config.TeamCustomerAnalyticsConfigSerializer(
            instance.customer_analytics_config,
            data=validated_data,
            partial=True,
            context={**self.context, "user_access_control": self.user_access_control},
        )
        if not serializer.is_valid():
            raise serializers.ValidationError(settings_validation._format_serializer_errors(serializer.errors))

        serializer.save()

        new_config = {
            field: getattr(instance.customer_analytics_config, field)
            for field in team_config.TeamCustomerAnalyticsConfigSerializer.Meta.fields
        }
        self._capture_diff(instance, "customer_analytics_config", old_config, new_config)
        return instance

    def _update_workflows_config(self, instance: Team, validated_data: dict[str, Any]) -> Team:
        old_config = {
            field: getattr(instance.workflows_config, field)
            for field in team_config.TeamWorkflowsConfigSerializer.Meta.fields
        }

        serializer = team_config.TeamWorkflowsConfigSerializer(
            instance.workflows_config,
            data=validated_data,
            partial=True,
            context={**self.context, "user_access_control": self.user_access_control},
        )
        if not serializer.is_valid():
            raise serializers.ValidationError(settings_validation._format_serializer_errors(serializer.errors))

        serializer.save()

        new_config = {
            field: getattr(instance.workflows_config, field)
            for field in team_config.TeamWorkflowsConfigSerializer.Meta.fields
        }
        self._capture_diff(instance, "workflows_config", old_config, new_config)
        return instance

    def _update_feature_flag_policy_config(self, instance: Team, validated_data: dict[str, Any]) -> Team:
        old_config = {
            field: getattr(instance.feature_flag_policy_config, field)
            for field in team_config.TeamFeatureFlagPolicyConfigSerializer.Meta.fields
        }

        serializer = team_config.TeamFeatureFlagPolicyConfigSerializer(
            instance.feature_flag_policy_config,
            data=validated_data,
            partial=True,
            context={**self.context, "user_access_control": self.user_access_control},
        )
        if not serializer.is_valid():
            raise serializers.ValidationError(settings_validation._format_serializer_errors(serializer.errors))

        serializer.save()

        new_config = {
            field: getattr(instance.feature_flag_policy_config, field)
            for field in team_config.TeamFeatureFlagPolicyConfigSerializer.Meta.fields
        }
        self._capture_diff(instance, "feature_flag_policy_config", old_config, new_config)
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
                was_impersonated=is_impersonated(self.context["request"]),
                scope="Team",
                item_id=instance.pk,
                activity="updated",
                detail=Detail(name=str(instance.name), changes=changes),
            )


class EvaluationContextSuggestionRequestSerializer(serializers.Serializer):
    context_name = serializers.CharField(
        max_length=255,
        help_text=(
            "Name of the evaluation context to hide from (POST) or restore to (DELETE) "
            "the flag editor's suggestion list. Case-insensitive and whitespace-trimmed."
        ),
    )


class EvaluationContextSuggestionResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(help_text="Whether the suggestion visibility change was applied.")
    name = serializers.CharField(help_text="Normalized name of the affected evaluation context.")
    hidden_from_suggestions = serializers.BooleanField(
        help_text="Whether the context is now hidden from the flag editor's suggestion list."
    )
