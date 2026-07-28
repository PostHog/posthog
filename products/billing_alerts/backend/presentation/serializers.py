from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from urllib.parse import urlparse

from django.db import transaction
from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from products.billing_alerts.backend.facade import api as billing_alerts_api
from products.billing_alerts.backend.facade.api import BillingAlertConfiguration, BillingAlertEvent

_DESTINATIONS_CACHE_KEY = "_billing_alert_destinations_by_alert_id"
_NOT_PROVIDED = object()


def _any_field_changed(
    instance: BillingAlertConfiguration,
    validated_data: dict[str, Any],
    fields: set[str],
) -> bool:
    return any(field in validated_data and validated_data[field] != getattr(instance, field) for field in fields)


def _is_microsoft_teams_webhook(webhook_url: str) -> bool:
    parsed = urlparse(webhook_url)
    hostname = parsed.hostname or ""
    path = parsed.path
    if hostname.endswith(".logic.azure.com"):
        return parsed.port in (None, 443) and path.startswith("/workflows/") and "/triggers/manual/paths/invoke" in path
    if hostname.endswith(".webhook.office.com"):
        return path.startswith("/webhookb2/") and "/IncomingWebhook/" in path
    if hostname.endswith((".powerautomate.com", ".flow.microsoft.com")):
        return bool(path.strip("/"))
    if hostname.endswith(".environment.api.powerplatform.com"):
        return path.startswith("/powerautomate/automations/direct/") and "/workflows/" in path
    return False


class BillingAlertEventSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this billing alert event.")
    kind = serializers.ChoiceField(
        choices=BillingAlertEvent.Kind.choices,
        read_only=True,
        help_text="Event kind for a check, state transition, or delivery-worthy alert event.",
    )
    source = serializers.ChoiceField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        choices=BillingAlertEvent.Source.choices,
        read_only=True,
        help_text="Whether this evaluation was scheduled or manually requested.",
    )
    attempt_number = serializers.IntegerField(
        read_only=True,
        help_text="Attempt number for this billing date and configuration revision.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When this event was recorded.")
    evaluation_date = serializers.DateField(
        read_only=True,
        allow_null=True,
        help_text="Billing data date evaluated by this event.",
    )
    configuration_revision = serializers.IntegerField(
        source="claim.configuration_revision",
        read_only=True,
        help_text="Configuration revision used for this evaluation.",
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
        max_digits=28,
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
            "source",
            "attempt_number",
            "created_at",
            "evaluation_date",
            "configuration_revision",
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


class BillingAlertDestinationSummarySerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["slack", "webhook", "teams"])
    hog_function_ids = serializers.ListField(child=serializers.UUIDField())


class BillingAlertDestinationCreateDataSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["slack", "webhook", "teams"], help_text="Destination type.")
    slack_workspace_id = serializers.IntegerField(
        required=False, help_text="Slack integration ID in the alert execution project."
    )
    slack_channel_id = serializers.CharField(required=False, help_text="Slack channel ID for alert delivery.")
    slack_channel_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Optional Slack channel name shown in the UI."
    )
    webhook_url = serializers.URLField(
        required=False, help_text="HTTPS webhook URL for webhook or Microsoft Teams delivery."
    )

    def validate(self, attrs: dict) -> dict:
        destination_type = attrs["type"]
        if destination_type == "slack":
            if not attrs.get("slack_workspace_id") or not attrs.get("slack_channel_id"):
                raise ValidationError("slack_workspace_id and slack_channel_id are required for slack destinations.")
        elif destination_type in ("webhook", "teams"):
            webhook_url = attrs.get("webhook_url")
            if not webhook_url:
                raise ValidationError(f"webhook_url is required for {destination_type} destinations.")
            parsed_url = urlparse(webhook_url)
            if parsed_url.scheme != "https" or not parsed_url.netloc:
                raise ValidationError({"webhook_url": "Webhook URLs must be valid HTTPS URLs."})
            if destination_type == "teams" and not _is_microsoft_teams_webhook(webhook_url):
                raise ValidationError({"webhook_url": "Enter a supported Microsoft Teams webhook URL."})
        return attrs


class BillingAlertDestinationChangesSerializer(serializers.Serializer):
    delete = serializers.ListField(
        child=serializers.ListField(
            child=serializers.UUIDField(),
            min_length=len(billing_alerts_api.BILLING_ALERT_EVENT_IDS),
            max_length=len(billing_alerts_api.BILLING_ALERT_EVENT_IDS),
        ),
        required=False,
        default=list,
    )

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["create"] = BillingAlertDestinationCreateDataSerializer(many=True, required=False, default=list)
        return fields


class BillingAlertConfigurationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this billing alert.")
    organization_id = serializers.UUIDField(read_only=True, help_text="Organization this billing alert belongs to.")
    execution_team_id = serializers.IntegerField(
        source="team_id",
        read_only=True,
        allow_null=True,
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
    name = serializers.CharField(max_length=160, help_text="Display name for this billing alert.")
    description = serializers.CharField(required=False, allow_blank=True, help_text="Optional internal description.")
    enabled = serializers.BooleanField(required=False, help_text="Whether scheduled checks should evaluate this alert.")
    metric = serializers.ChoiceField(
        choices=BillingAlertConfiguration.Metric.choices,
        read_only=True,
        help_text="Billing metric evaluated by this alert. The first version supports spend only.",
    )
    currency = serializers.CharField(read_only=True, help_text="Server-controlled currency for spend values.")
    configuration_revision = serializers.IntegerField(
        read_only=True,
        help_text="Revision incremented whenever evaluation behavior changes.",
    )
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
    baseline_window_days = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=90,
        help_text="Number of preceding UTC billing dates averaged for relative and absolute increase baselines.",
    )
    evaluation_delay_hours = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=72,
        help_text="Hours after a UTC billing date ends before it becomes eligible for evaluation.",
    )
    state = serializers.ChoiceField(choices=BillingAlertConfiguration.State.choices, read_only=True)
    check_interval_hours = serializers.ChoiceField(
        choices=[billing_alerts_api.DAILY_CHECK_INTERVAL_HOURS],
        required=False,
        help_text="Billing alerts evaluate one UTC billing date per day.",
    )
    cooldown_hours = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=24 * 30,
        help_text="Minimum hours between repeated firing notifications.",
    )
    snooze_until = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="ISO 8601 timestamp until which evaluation and notifications are snoozed, or null to resume.",
    )
    next_check_at = serializers.DateTimeField(read_only=True, allow_null=True)
    last_checked_at = serializers.DateTimeField(read_only=True, allow_null=True)
    last_notified_at = serializers.DateTimeField(read_only=True, allow_null=True)
    consecutive_failures = serializers.IntegerField(read_only=True)
    destinations = serializers.SerializerMethodField(
        help_text="Notification destination groups configured for this alert, including their shared HogFunctions.",
    )
    destination_changes = BillingAlertDestinationChangesSerializer(
        required=False,
        write_only=True,
        help_text="Destination groups to create or delete in the same transaction as this configuration write.",
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
            "name",
            "description",
            "enabled",
            "metric",
            "currency",
            "configuration_revision",
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
            "destinations",
            "destination_changes",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(BillingAlertDestinationSummarySerializer(many=True))
    def get_destinations(self, obj: BillingAlertConfiguration) -> list[dict[str, Any]]:
        cache = self.context.get(_DESTINATIONS_CACHE_KEY)
        if cache is None:
            alerts = self._destination_cache_alerts(obj)
            cache = billing_alerts_api.destinations_for_alerts(alerts)
            self.context[_DESTINATIONS_CACHE_KEY] = cache
        destinations_by_alert_id = cast(dict[str, list[dict[str, Any]]], cache)
        return destinations_by_alert_id.get(str(obj.id), [])

    def _destination_cache_alerts(self, obj: BillingAlertConfiguration) -> list[BillingAlertConfiguration]:
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
        if attrs.get("enabled") is False and attrs.get("snooze_until") is not None:
            raise ValidationError({"snooze_until": "A disabled alert cannot also be snoozed."})
        return attrs

    def create(self, validated_data: dict[str, Any]) -> BillingAlertConfiguration:
        destination_changes = validated_data.pop("destination_changes", None)
        with transaction.atomic():
            alert = super().create(validated_data)
            billing_alerts_api.initialize_billing_alert_lifecycle(alert)
            if destination_changes:
                billing_alerts_api.apply_destination_changes(
                    alert, request=self.context["request"], changes=destination_changes
                )
            return alert

    def update(
        self,
        instance: BillingAlertConfiguration,
        validated_data: dict[str, Any],
    ) -> BillingAlertConfiguration:
        destination_changes = validated_data.pop("destination_changes", None)
        snooze_until = validated_data.get("snooze_until", _NOT_PROVIDED)
        evaluation_fields = {
            "threshold_type",
            "threshold_percentage",
            "threshold_value",
            "minimum_value",
            "baseline_window_days",
            "evaluation_delay_hours",
        }
        revision_fields = evaluation_fields | {
            "enabled",
            "snooze_until",
            "check_interval_hours",
            "cooldown_hours",
        }
        with transaction.atomic():
            locked = BillingAlertConfiguration.objects.select_for_update().get(
                pk=instance.pk,
                organization_id=instance.organization_id,
            )
            evaluation_changed = _any_field_changed(locked, validated_data, evaluation_fields)
            cadence_changed = _any_field_changed(locked, validated_data, {"check_interval_hours"})
            configuration_changed = _any_field_changed(
                locked,
                validated_data,
                revision_fields,
            )
            enabled_change: bool | None = None
            if "enabled" in validated_data and validated_data["enabled"] != locked.enabled:
                enabled_change = validated_data["enabled"]

            billing_alerts_api.apply_billing_alert_configuration_lifecycle(
                locked,
                enabled_change=enabled_change,
                snooze_until_provided=snooze_until is not _NOT_PROVIDED,
                snooze_until=snooze_until if snooze_until is not _NOT_PROVIDED else None,
                threshold_changed=evaluation_changed,
            )

            updated = super().update(locked, validated_data)
            billing_alerts_api.reschedule_billing_alert_configuration(
                updated,
                configuration_changed=configuration_changed,
                cadence_changed=cadence_changed,
            )
            if destination_changes:
                billing_alerts_api.apply_destination_changes(
                    updated, request=self.context["request"], changes=destination_changes
                )
            return updated


class BillingAlertCreateDestinationSerializer(BillingAlertDestinationCreateDataSerializer):
    def validate(self, attrs: dict) -> dict:
        attrs = super().validate(attrs)
        alert = self.context.get("alert")
        if (
            attrs["type"] == "slack"
            and alert is not None
            and not billing_alerts_api.slack_integration_belongs_to_team(
                integration_id=attrs["slack_workspace_id"],
                team_id=alert.execution_team_id,
            )
        ):
            raise ValidationError(
                {"slack_workspace_id": "Slack integration does not belong to this billing alert execution team."}
            )
        return attrs


class BillingAlertDeleteDestinationSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=len(billing_alerts_api.BILLING_ALERT_EVENT_IDS),
        max_length=len(billing_alerts_api.BILLING_ALERT_EVENT_IDS),
        help_text="HogFunction IDs to delete as one atomic destination group.",
    )


class BillingAlertDestinationResponseSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(child=serializers.UUIDField())


class BillingAlertCheckNowResponseSerializer(serializers.Serializer):
    event = BillingAlertEventSerializer(help_text="Evaluation event recorded by the manual check.")
    dispatched_destinations = serializers.IntegerField(help_text="Number of destination HogFunctions queued.")
