from django.db.models import Prefetch, QuerySet

from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import PostHogFeatureFlagPermission

from products.alerts.backend.models.platform_alert import PlatformAlert, PlatformAlertConfiguration
from products.alerts.backend.presentation.views.alert import ScheduleRestrictionField


class PlatformAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformAlert
        fields = ["id", "grouping_key", "state", "firing_started_at", "last_notified_at", "snooze_until"]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Unique identifier of this alert instance."},
            "grouping_key": {
                "help_text": "Key of the result group this instance tracks. Empty when the source does not group results."
            },
            "state": {"help_text": "Current state of this alert instance."},
            "firing_started_at": {
                "help_text": "When the current firing started. Null when the instance is not firing."
            },
            "last_notified_at": {"help_text": "When a notification was last sent for this instance."},
            "snooze_until": {"help_text": "Time until which notifications are snoozed. Null when not snoozed."},
        }


class PlatformAlertConfigurationSerializer(serializers.ModelSerializer):
    source_config = serializers.DictField(
        child=serializers.JSONField(),
        read_only=True,
        help_text="Source-specific query settings. The shape depends on source_kind.",
    )
    schedule_restriction = ScheduleRestrictionField(
        read_only=True,
        allow_null=True,
        help_text="Blocked local time windows (HH:MM in the project timezone) when the alert does not run. "
        "Null means no quiet hours.",
    )
    alerts = PlatformAlertSerializer(
        many=True,
        read_only=True,
        help_text="Runtime state for each result group of this configuration.",
    )

    class Meta:
        model = PlatformAlertConfiguration
        fields = [
            "id",
            "name",
            "enabled",
            "source_kind",
            "source_config",
            "threshold_count",
            "threshold_operator",
            "window_minutes",
            "check_interval_minutes",
            "evaluation_periods",
            "datapoints_to_alarm",
            "cooldown_minutes",
            "schedule_restriction",
            "next_check_at",
            "consecutive_failures",
            "legacy_configuration_id",
            "created_at",
            "updated_at",
            "alerts",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Unique identifier of the alert configuration."},
            "name": {"help_text": "Human-readable name of the alert."},
            "enabled": {"help_text": "Whether the alert is evaluated on schedule."},
            "source_kind": {"help_text": "Product whose data the alert evaluates."},
            "threshold_count": {"help_text": "Count the evaluated value is compared against."},
            "threshold_operator": {"help_text": "Comparison operator applied between the value and threshold_count."},
            "window_minutes": {"help_text": "Length of the evaluated time window, in minutes."},
            "check_interval_minutes": {"help_text": "Minutes between scheduled checks."},
            "evaluation_periods": {"help_text": "Number of recent checks considered when deciding to fire."},
            "datapoints_to_alarm": {
                "help_text": "Number of breaching checks within evaluation_periods required to fire."
            },
            "cooldown_minutes": {"help_text": "Minimum minutes between notifications for the same alert."},
            "next_check_at": {"help_text": "When the next check is due. Null when no check is scheduled."},
            "consecutive_failures": {"help_text": "Number of checks in a row that failed to evaluate."},
            "legacy_configuration_id": {
                "help_text": "ID of the legacy source configuration this row was backfilled from. "
                "Null for alerts created on the platform."
            },
            "created_at": {"help_text": "When the configuration was created."},
            "updated_at": {"help_text": "When the configuration was last changed."},
        }


class PlatformAlertConfigurationViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "alert"
    serializer_class = PlatformAlertConfigurationSerializer
    posthog_feature_flag = "platform-alerts"
    permission_classes = [PostHogFeatureFlagPermission]
    # The fail-closed manager raises if `.all()` runs at import, so scoping happens in
    # safely_get_queryset.
    queryset = PlatformAlertConfiguration.objects.unscoped()

    def _should_skip_parents_filter(self) -> bool:
        # for_team() resolves a child environment to its parent team, where the rows live. The
        # default parent-lookup filter would AND the raw URL team id back in and hide them.
        return True

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return (
            PlatformAlertConfiguration.objects.for_team(self.team_id)
            .prefetch_related(
                Prefetch("alerts", queryset=PlatformAlert.objects.for_team(self.team_id).order_by("grouping_key"))
            )
            .order_by("-created_at")
        )
