from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from urllib.parse import urlparse

from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from posthog.api.shared import UserBasicSerializer
from posthog.models.user import User

from products.billing_alerts.backend.facade import api as billing_alerts_api
from products.billing_alerts.backend.facade.api import BillingAlertConfiguration, BillingAlertEvent

_DESTINATION_TYPES_CACHE_KEY = "_billing_alert_destination_types_by_alert_id"


class BillingAlertEventSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this billing alert event.")
    kind = serializers.ChoiceField(
        choices=BillingAlertEvent.Kind.choices,
        read_only=True,
        help_text="Event kind for a check, state transition, or delivery-worthy alert event.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When this event was recorded.")
    evaluation_date = serializers.DateField(
        read_only=True,
        allow_null=True,
        help_text="Billing data date evaluated by this event.",
    )
    period_start = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="Start of the evaluated billing period.",
    )
    period_end = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="End of the evaluated billing period.",
    )
    metric = serializers.ChoiceField(
        choices=BillingAlertConfiguration.Metric.choices,
        read_only=True,
        help_text="Billing metric evaluated by this event.",
    )
    current_value = serializers.DecimalField(max_digits=20, decimal_places=6, read_only=True, allow_null=True)
    baseline_value = serializers.DecimalField(max_digits=20, decimal_places=6, read_only=True, allow_null=True)
    absolute_delta = serializers.DecimalField(max_digits=20, decimal_places=6, read_only=True, allow_null=True)
    relative_delta_percentage = serializers.DecimalField(
        max_digits=12,
        decimal_places=6,
        read_only=True,
        allow_null=True,
    )
    threshold_breached = serializers.BooleanField(read_only=True)
    state_before = serializers.CharField(read_only=True, allow_null=True)
    state_after = serializers.CharField(read_only=True, allow_null=True)
    notification_sent_at = serializers.DateTimeField(read_only=True, allow_null=True)
    targets_notified = serializers.JSONField(read_only=True)
    query_duration_ms = serializers.IntegerField(read_only=True, allow_null=True)
    error_code = serializers.CharField(read_only=True, allow_null=True)
    error_message = serializers.CharField(read_only=True, allow_null=True)
    reason = serializers.CharField(read_only=True)

    class Meta:
        model = BillingAlertEvent
        fields = [
            "id",
            "kind",
            "created_at",
            "evaluation_date",
            "period_start",
            "period_end",
            "metric",
            "current_value",
            "baseline_value",
            "absolute_delta",
            "relative_delta_percentage",
            "threshold_breached",
            "state_before",
            "state_after",
            "notification_sent_at",
            "targets_notified",
            "query_duration_ms",
            "error_code",
            "error_message",
            "reason",
        ]


class BillingAlertConfigurationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this billing alert.")
    organization_id = serializers.UUIDField(read_only=True, help_text="Organization this billing alert belongs to.")
    execution_team_id = serializers.IntegerField(
        source="team_id",
        read_only=True,
        help_text="Team used as the execution context for internal notification destinations.",
    )
    created_by_id = serializers.IntegerField(
        read_only=True, allow_null=True, help_text="User ID that created this alert."
    )
    updated_by_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="User ID that last updated this alert.",
    )
    created_by = serializers.SerializerMethodField(help_text="User that created this alert, or null if unavailable.")
    updated_by = serializers.SerializerMethodField(
        help_text="User that last updated this alert, or null if unavailable."
    )
    name = serializers.CharField(max_length=160, help_text="Display name for this billing alert.")
    description = serializers.CharField(required=False, allow_blank=True, help_text="Optional internal description.")
    enabled = serializers.BooleanField(required=False, help_text="Whether scheduled checks should evaluate this alert.")
    metric = serializers.ChoiceField(
        choices=BillingAlertConfiguration.Metric.choices,
        required=False,
        help_text="Billing metric to evaluate: spend or usage.",
    )
    currency = serializers.CharField(max_length=3, required=False, help_text="Currency for spend alerts.")
    threshold_type = serializers.ChoiceField(
        choices=BillingAlertConfiguration.ThresholdType.choices,
        required=False,
        help_text="Threshold rule type.",
    )
    threshold_percentage = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        required=False,
        allow_null=True,
        help_text="Percentage increase that triggers relative increase alerts.",
    )
    threshold_value = serializers.DecimalField(
        max_digits=20,
        decimal_places=6,
        required=False,
        allow_null=True,
        help_text="Absolute value or absolute increase that triggers absolute threshold alerts.",
    )
    minimum_value = serializers.DecimalField(
        max_digits=20,
        decimal_places=6,
        required=False,
        help_text="Minimum current value before the alert can fire.",
    )
    baseline_window_days = serializers.IntegerField(required=False, min_value=1, max_value=90)
    evaluation_delay_hours = serializers.IntegerField(required=False, min_value=0, max_value=72)
    state = serializers.ChoiceField(choices=BillingAlertConfiguration.State.choices, read_only=True)
    check_interval_hours = serializers.IntegerField(required=False, min_value=1, max_value=24)
    cooldown_hours = serializers.IntegerField(required=False, min_value=0, max_value=24 * 30)
    snooze_until = serializers.DateTimeField(required=False, allow_null=True)
    next_check_at = serializers.DateTimeField(read_only=True, allow_null=True)
    last_checked_at = serializers.DateTimeField(read_only=True, allow_null=True)
    last_notified_at = serializers.DateTimeField(read_only=True, allow_null=True)
    consecutive_failures = serializers.IntegerField(read_only=True)
    destination_types = serializers.SerializerMethodField(
        help_text="Notification destination types configured for this alert.",
    )
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = BillingAlertConfiguration
        fields = [
            "id",
            "organization_id",
            "execution_team_id",
            "created_by_id",
            "updated_by_id",
            "created_by",
            "updated_by",
            "name",
            "description",
            "enabled",
            "metric",
            "currency",
            "threshold_type",
            "threshold_percentage",
            "threshold_value",
            "minimum_value",
            "baseline_window_days",
            "evaluation_delay_hours",
            "state",
            "check_interval_hours",
            "cooldown_hours",
            "snooze_until",
            "next_check_at",
            "last_checked_at",
            "last_notified_at",
            "consecutive_failures",
            "destination_types",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.ListField(child=serializers.ChoiceField(choices=["slack", "webhook", "teams"])))
    def get_destination_types(self, obj: BillingAlertConfiguration) -> list[str]:
        cache = self.context.get(_DESTINATION_TYPES_CACHE_KEY)
        if cache is None:
            cache = self._load_destination_type_cache(obj)
            self.context[_DESTINATION_TYPES_CACHE_KEY] = cache
        destination_types_by_alert_id = cast(dict[str, list[str]], cache)
        alert_id = str(obj.id)
        if alert_id not in destination_types_by_alert_id:
            destination_types_by_alert_id.update(self._load_destination_type_cache(obj))
        return destination_types_by_alert_id.get(alert_id, [])

    def _load_destination_type_cache(self, obj: BillingAlertConfiguration) -> dict[str, list[str]]:
        alerts = self._destination_type_cache_alerts(obj)
        return billing_alerts_api.destination_types_for_alerts(alerts)

    def _destination_type_cache_alerts(self, obj: BillingAlertConfiguration) -> list[BillingAlertConfiguration]:
        parent_instance = getattr(getattr(self, "parent", None), "instance", None)
        instance = parent_instance if parent_instance is not None else self.instance

        if isinstance(instance, BillingAlertConfiguration):
            return [instance]
        if isinstance(instance, QuerySet):
            return [item for item in instance if isinstance(item, BillingAlertConfiguration)]
        if instance is not None:
            try:
                alerts = [item for item in instance if isinstance(item, BillingAlertConfiguration)]
                if alerts:
                    return alerts
            except TypeError:
                pass
        return [obj]

    @extend_schema_field(UserBasicSerializer(allow_null=True))
    def get_created_by(self, obj: BillingAlertConfiguration) -> dict[str, Any] | None:
        return self._serialize_user(obj.created_by_id)

    @extend_schema_field(UserBasicSerializer(allow_null=True))
    def get_updated_by(self, obj: BillingAlertConfiguration) -> dict[str, Any] | None:
        return self._serialize_user(obj.updated_by_id)

    def _serialize_user(self, user_id: int | None) -> dict[str, Any] | None:
        if user_id is None:
            return None

        cache: dict[int, dict[str, Any] | None] = self.context.setdefault("_billing_alert_user_cache", {})
        if user_id not in cache:
            user = (
                User.objects.filter(id=user_id)
                .only(
                    "id",
                    "uuid",
                    "distinct_id",
                    "first_name",
                    "last_name",
                    "email",
                    "is_email_verified",
                    "role_at_organization",
                    "hedgehog_config",
                )
                .first()
            )
            cache[user_id] = dict(UserBasicSerializer(user, context=self.context).data) if user else None
        return cache[user_id]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        current = self.instance
        threshold_type = attrs.get(
            "threshold_type",
            current.threshold_type if current else BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
        )
        threshold_percentage = attrs.get(
            "threshold_percentage",
            current.threshold_percentage if current else None,
        )
        threshold_value = attrs.get("threshold_value", current.threshold_value if current else None)
        minimum_value = attrs.get("minimum_value", current.minimum_value if current else Decimal("0"))

        if threshold_type == BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE:
            if threshold_percentage is None:
                raise ValidationError({"threshold_percentage": "Required for relative increase alerts."})
            if threshold_percentage <= 0:
                raise ValidationError({"threshold_percentage": "Must be greater than 0."})
        if threshold_type in (
            BillingAlertConfiguration.ThresholdType.ABSOLUTE_VALUE,
            BillingAlertConfiguration.ThresholdType.ABSOLUTE_INCREASE,
        ):
            if threshold_value is None:
                raise ValidationError({"threshold_value": "Required for absolute threshold alerts."})
            if threshold_value < 0:
                raise ValidationError({"threshold_value": "Must be greater than or equal to 0."})
        if minimum_value < 0:
            raise ValidationError({"minimum_value": "Must be greater than or equal to 0."})
        return attrs


class BillingAlertCreateDestinationSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["slack", "webhook", "teams"], help_text="Destination type.")
    slack_workspace_id = serializers.IntegerField(
        required=False,
        help_text="Integration ID for the Slack workspace. Required when type=slack.",
    )
    slack_channel_id = serializers.CharField(required=False, help_text="Slack channel ID. Required when type=slack.")
    slack_channel_name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Human-readable channel name for display.",
    )
    webhook_url = serializers.URLField(
        required=False,
        help_text="HTTPS endpoint to POST to. Required when type=webhook, or the Teams webhook URL when type=teams.",
    )

    def validate(self, attrs: dict) -> dict:
        destination_type = attrs["type"]
        if destination_type == "slack":
            if not attrs.get("slack_workspace_id") or not attrs.get("slack_channel_id"):
                raise ValidationError("slack_workspace_id and slack_channel_id are required for slack destinations.")
            alert = self.context.get("alert")
            if alert is not None and not billing_alerts_api.slack_integration_belongs_to_team(
                integration_id=attrs["slack_workspace_id"],
                team_id=alert.execution_team_id,
            ):
                raise ValidationError(
                    {"slack_workspace_id": "Slack integration does not belong to this billing alert execution team."}
                )
        elif destination_type in ("webhook", "teams"):
            webhook_url = attrs.get("webhook_url")
            if not webhook_url:
                raise ValidationError(f"webhook_url is required for {destination_type} destinations.")
            parsed_url = urlparse(webhook_url)
            if parsed_url.scheme != "https" or not parsed_url.netloc:
                raise ValidationError({"webhook_url": "Webhook URLs must be valid HTTPS URLs."})
        return attrs


class BillingAlertDeleteDestinationSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        help_text="HogFunction IDs to delete as one atomic destination group.",
    )


class BillingAlertDestinationResponseSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(child=serializers.UUIDField())


class BillingAlertCheckNowResponseSerializer(serializers.Serializer):
    event = BillingAlertEventSerializer(help_text="Evaluation event recorded by the manual check.")
    dispatched_destinations = serializers.IntegerField(help_text="Number of destination HogFunctions queued.")
