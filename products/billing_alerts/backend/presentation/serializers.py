from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from urllib.parse import urlparse

from django.db import transaction
from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from products.alerts.backend.facade.api import (
    AlertDestinationData,
    AlertDestinationValidationError,
    DestinationType,
    validate_destination_data,
)
from products.billing_alerts.backend.facade import api as billing_alerts_api
from products.billing_alerts.backend.facade.api import (
    BillingAlertConfiguration,
    BillingAlertEvent,
    validate_threshold_configuration,
)

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
    # Model properties derived from the claim, so DRF cannot generate them.
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
        read_only_fields = [field for field in fields if field not in ("evaluation_date", "configuration_revision")]
        extra_kwargs = {
            "id": {"help_text": "Unique identifier for this billing alert event."},
            "kind": {"help_text": "Event kind for a check, state transition, or delivery-worthy alert event."},
            "source": {"help_text": "Whether this evaluation was scheduled or manually requested."},
            "attempt_number": {"help_text": "Attempt number for this billing date and configuration revision."},
            "created_at": {"help_text": "When this event was recorded."},
            "period_start": {"help_text": "Start of the evaluated billing period."},
            "period_end": {"help_text": "End of the evaluated billing period."},
            "metric": {"help_text": "Billing metric evaluated by this event."},
            "current_value": {"help_text": "Metric value for the evaluated billing date."},
            "baseline_value": {"help_text": "Average metric value across the baseline window."},
            "absolute_delta": {"help_text": "Current value minus the baseline value."},
            "relative_delta_percentage": {"help_text": "Percentage change against the baseline value."},
            "threshold_breached": {"help_text": "Whether the evaluated value breached the configured threshold."},
            "state_before": {"help_text": "Alert state before this event was applied."},
            "state_after": {"help_text": "Alert state after this event was applied."},
            "notification_sent_at": {"help_text": "When notifications for this event were delivered."},
            "targets_notified": {"help_text": "Notification targets recorded for this event."},
            "query_duration_ms": {"help_text": "Milliseconds spent fetching billing data for this evaluation."},
            "error_code": {"help_text": "Exception class name recorded when the evaluation failed."},
            "error_message": {"help_text": "Failure description recorded when the evaluation failed."},
            "reason": {"help_text": "Human-readable explanation of the evaluation outcome."},
        }


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
        data = cast(AlertDestinationData, attrs)
        data["type"] = DestinationType(attrs["type"])
        try:
            validate_destination_data(data, allowed_destination_types=billing_alerts_api.BILLING_DESTINATION_TYPES)
        except AlertDestinationValidationError as error:
            if error.field:
                raise ValidationError({error.field: error.message})
            raise ValidationError(error.message)

        # URL-shape checks beyond the shared required-field validation.
        webhook_url = attrs.get("webhook_url")
        if data["type"] in (DestinationType.WEBHOOK, DestinationType.TEAMS) and webhook_url:
            parsed_url = urlparse(webhook_url)
            if parsed_url.scheme != "https" or not parsed_url.netloc:
                raise ValidationError({"webhook_url": "Webhook URLs must be valid HTTPS URLs."})
            if data["type"] == DestinationType.TEAMS and not _is_microsoft_teams_webhook(webhook_url):
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
    cooldown_hours = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=24 * 30,
        help_text="Minimum hours between repeated firing notifications.",
    )
    snoozed_until = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="ISO 8601 timestamp until which evaluation and notifications are snoozed, or null to resume.",
    )
    destinations = serializers.SerializerMethodField(
        help_text="Notification destination groups configured for this alert, including their shared HogFunctions.",
    )
    destination_changes = BillingAlertDestinationChangesSerializer(
        required=False,
        write_only=True,
        help_text="Destination groups to create or delete in the same transaction as this configuration write.",
    )

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
            "cooldown_hours",
            "snoozed_until",
            "next_check_at",
            "last_checked_at",
            "last_notified_at",
            "consecutive_failures",
            "destinations",
            "destination_changes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "metric",
            "currency",
            "configuration_revision",
            "state",
            "next_check_at",
            "last_checked_at",
            "last_notified_at",
            "consecutive_failures",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "metric": {"help_text": "Billing metric evaluated by this alert. The first version supports spend only."},
            "currency": {"help_text": "Server-controlled currency for spend values."},
            "configuration_revision": {"help_text": "Revision incremented whenever evaluation behavior changes."},
            "state": {"help_text": "Current lifecycle state of this alert."},
            "next_check_at": {"help_text": "When the next scheduled evaluation is due."},
            "last_checked_at": {"help_text": "When this alert was last evaluated."},
            "last_notified_at": {"help_text": "When notifications were last delivered for this alert."},
            "consecutive_failures": {"help_text": "Number of consecutive failed evaluations."},
            "created_at": {"help_text": "When this alert was created."},
            "updated_at": {"help_text": "When this alert was last updated."},
        }

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
        if isinstance(instance, QuerySet | list):
            alerts = [item for item in instance if isinstance(item, BillingAlertConfiguration)]
            if alerts:
                return alerts
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

        errors = validate_threshold_configuration(
            threshold_type=threshold_type,
            threshold_percentage=threshold_percentage,
            threshold_value=threshold_value,
            minimum_value=minimum_value,
        )
        if errors:
            raise ValidationError(errors)

        enabled = attrs.get("enabled", current.enabled if current else True)
        if attrs.get("snoozed_until") is not None and not enabled:
            raise ValidationError({"snoozed_until": "A disabled alert cannot also be snoozed."})
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
        snoozed_until = validated_data.get("snoozed_until", _NOT_PROVIDED)
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
            "snoozed_until",
            "cooldown_hours",
        }
        with transaction.atomic():
            locked = BillingAlertConfiguration.objects.select_for_update().get(
                pk=instance.pk,
                organization_id=instance.organization_id,
            )
            evaluation_changed = _any_field_changed(locked, validated_data, evaluation_fields)
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
                snoozed_until_provided=snoozed_until is not _NOT_PROVIDED,
                snoozed_until=snoozed_until if snoozed_until is not _NOT_PROVIDED else None,
                threshold_changed=evaluation_changed,
            )

            updated = super().update(locked, validated_data)
            billing_alerts_api.reschedule_billing_alert_configuration(
                updated,
                configuration_changed=configuration_changed,
            )
            if destination_changes:
                billing_alerts_api.apply_destination_changes(
                    updated, request=self.context["request"], changes=destination_changes
                )
            return updated


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
