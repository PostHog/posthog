from typing import Any

from croniter import croniter  # type: ignore[import-untyped,unused-ignore]
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, viewsets

from posthog.api.feature_flag import CanEditFeatureFlag
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import ScheduledChange


class ScheduledChangeSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    failure_reason = serializers.SerializerMethodField()

    record_id = serializers.CharField(
        max_length=200,
        help_text="The ID of the record to modify (e.g. the feature flag ID).",
    )
    model_name = serializers.ChoiceField(
        choices=ScheduledChange.AllowedModels.choices,
        help_text='The type of record to modify. Currently only "FeatureFlag" is supported.',
    )
    payload = serializers.JSONField(
        help_text=(
            "The change to apply. Must include an 'operation' key and a 'value' key. "
            "Supported operations: 'update_status' (value: true/false to enable/disable the flag), "
            "'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), "
            "'update_variants' (value: object with 'variants' and 'payloads' keys)."
        ),
    )
    scheduled_at = serializers.DateTimeField(
        help_text="ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z').",
    )
    is_recurring = serializers.BooleanField(
        default=False,
        help_text="Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules.",
    )
    recurrence_interval = serializers.ChoiceField(
        choices=ScheduledChange.RecurrenceInterval.choices,
        required=False,
        allow_null=True,
        help_text="How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.",
    )
    end_date = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Optional ISO 8601 datetime after which a recurring schedule stops executing.",
    )

    class Meta:
        model = ScheduledChange
        fields = [
            "id",
            "team_id",
            "record_id",
            "model_name",
            "payload",
            "scheduled_at",
            "executed_at",
            "failure_reason",
            "created_at",
            "created_by",
            "updated_at",
            "is_recurring",
            "recurrence_interval",
            "cron_expression",
            "last_executed_at",
            "end_date",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "updated_at",
            "last_executed_at",
            "executed_at",
        ]

    def get_failure_reason(self, obj: ScheduledChange) -> str | None:
        """Return the safely formatted failure reason instead of raw data."""
        if not obj.failure_reason:
            return None
        return obj.formatted_failure_reason

    def validate(self, data: dict) -> dict:
        instance = getattr(self, "instance", None)

        # Prevent changing the target record on updates (defense in depth against cross-tenant manipulation)
        if instance:
            if "record_id" in data and str(data["record_id"]) != str(instance.record_id):
                raise serializers.ValidationError(
                    {"record_id": "Cannot change the target record of an existing scheduled change."}
                )
            if "model_name" in data and data["model_name"] != instance.model_name:
                raise serializers.ValidationError(
                    {"model_name": "Cannot change the model type of an existing scheduled change."}
                )

            # A completed one-time schedule is immutable. Recurring schedules legitimately carry
            # executed_at=NULL while active, so this guard only trips for one-time completions.
            if instance.executed_at is not None and not instance.is_recurring:
                raise serializers.ValidationError("Cannot modify a scheduled change that has already executed.")

        # For updates, merge with existing instance values
        is_recurring = data.get("is_recurring", getattr(instance, "is_recurring", False) if instance else False)
        recurrence_interval = data.get(
            "recurrence_interval", getattr(instance, "recurrence_interval", None) if instance else None
        )
        cron_expression = data.get("cron_expression", getattr(instance, "cron_expression", None) if instance else None)
        payload = data.get("payload", getattr(instance, "payload", {}) if instance else {})

        # cron_expression and recurrence_interval are mutually exclusive
        if cron_expression and recurrence_interval:
            raise serializers.ValidationError(
                {"cron_expression": "Cannot set both cron_expression and recurrence_interval. Use one or the other."}
            )

        # Validate cron expression syntax (only standard 5-field expressions are allowed)
        if cron_expression:
            parts = cron_expression.strip().split()
            if len(parts) != 5:
                raise serializers.ValidationError(
                    {
                        "cron_expression": "Only standard 5-field cron expressions are supported "
                        "(minute hour day month weekday). Example: '0 9 * * 1-5'."
                    }
                )
            if not croniter.is_valid(cron_expression):
                raise serializers.ValidationError(
                    {
                        "cron_expression": "Invalid cron expression. Use standard 5-field cron syntax (e.g., '0 9 * * 1-5')."
                    }
                )

        if is_recurring:
            if not recurrence_interval and not cron_expression:
                raise serializers.ValidationError(
                    {
                        "recurrence_interval": "Either recurrence_interval or cron_expression is required when is_recurring is true."
                    }
                )
            # Validate recurrence_interval is a valid choice (when using interval mode)
            if recurrence_interval:
                valid_intervals = [choice[0] for choice in ScheduledChange.RecurrenceInterval.choices]
                if recurrence_interval not in valid_intervals:
                    raise serializers.ValidationError(
                        {"recurrence_interval": f"Must be one of: {', '.join(valid_intervals)}"}
                    )
            # Recurring add_release_condition is not supported because it appends
            # condition groups on each run, creating duplicates.
            if payload.get("operation") == ScheduledChange.OperationType.ADD_RELEASE_CONDITION:
                raise serializers.ValidationError(
                    {
                        "payload": "Recurring schedules are not supported for add_release_condition "
                        "because it appends conditions on each run, creating duplicates."
                    }
                )
        # For new schedules (create), if is_recurring is false, recurrence config must be null.
        # We only preserve recurrence config when is_recurring=false for UPDATES (pausing existing schedules).
        if not instance and not is_recurring:
            if recurrence_interval:
                raise serializers.ValidationError(
                    {
                        "recurrence_interval": "Cannot set recurrence_interval when is_recurring is false for new schedules."
                    }
                )
            if cron_expression:
                raise serializers.ValidationError(
                    {"cron_expression": "Cannot set cron_expression when is_recurring is false for new schedules."}
                )

        # Validate end_date is after scheduled_at
        end_date = data.get("end_date", getattr(instance, "end_date", None) if instance else None)
        scheduled_at = data.get("scheduled_at", getattr(instance, "scheduled_at", None) if instance else None)
        if end_date and scheduled_at and end_date <= scheduled_at:
            raise serializers.ValidationError({"end_date": "End date must be after the scheduled start date."})

        return data

    def _check_target_edit_permission(self, model_name: str | None, record_id: Any, team_id: int) -> None:
        """Raise ValidationError unless the request user can edit the target record."""
        if model_name != "FeatureFlag" or not record_id:
            return

        from posthog.models import FeatureFlag

        try:
            feature_flag = FeatureFlag.objects.get(id=record_id, team_id=team_id)
        except FeatureFlag.DoesNotExist:
            raise serializers.ValidationError("Feature flag not found")

        request = self.context["request"]
        if not CanEditFeatureFlag().has_object_permission(request, None, feature_flag):
            raise serializers.ValidationError("You don't have edit permissions for this feature flag")

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> ScheduledChange:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]

        self._check_target_edit_permission(
            validated_data.get("model_name"), validated_data.get("record_id"), validated_data["team_id"]
        )

        return super().create(validated_data)

    def update(self, instance: ScheduledChange, validated_data: dict) -> ScheduledChange:
        # Enforce the same edit-permission check on updates. record_id/model_name can't be changed
        # (blocked in validate()), so the instance's existing target is authoritative.
        self._check_target_edit_permission(instance.model_name, instance.record_id, instance.team_id)
        return super().update(instance, validated_data)


@extend_schema(tags=["feature_flags"])
class ScheduledChangeViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, read, update and delete scheduled changes.
    """

    scope_object = "INTERNAL"
    serializer_class = ScheduledChangeSerializer
    queryset = ScheduledChange.objects.all()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "model_name",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Filter by model type. Use "FeatureFlag" to see feature flag schedules.',
            ),
            OpenApiParameter(
                "record_id",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by the ID of a specific feature flag.",
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def safely_get_queryset(self, queryset):
        model_name = self.request.query_params.get("model_name")
        record_id = self.request.query_params.get("record_id")

        if model_name is not None:
            queryset = queryset.filter(model_name=model_name)
        if record_id is not None:
            queryset = queryset.filter(record_id=record_id)

        return queryset
