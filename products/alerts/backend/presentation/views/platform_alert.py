from django.db.models import Prefetch, QuerySet

from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import PostHogFeatureFlagPermission, get_authenticator_scopes
from posthog.scopes import APIScopeObject, scopes_not_covered

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


# A configuration shows the source product's data (its filters and firing state), so a reader
# also needs read access to that product. `alert:read` alone must not reveal it.
SOURCE_KIND_RESOURCE: dict[str, APIScopeObject] = {
    PlatformAlertConfiguration.SourceKind.LOGS: "logs",
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
        # safely_get_queryset scopes a child environment to its parent team, where the rows live. The
        # default parent-lookup filter would AND the raw URL team id back in and hide them.
        return True

    def _readable_source_kinds(self) -> list[str]:
        # Session auth carries no scopes, so only the access-control check applies to it.
        token_scopes = get_authenticator_scopes(getattr(self.request, "successful_authenticator", None))
        readable: list[str] = []
        for source_kind, resource in SOURCE_KIND_RESOURCE.items():
            if not self.user_access_control.check_access_level_for_resource(resource, "viewer"):
                continue
            if (
                token_scopes is not None
                and "*" not in token_scopes
                and scopes_not_covered(token_scopes, [f"{resource}:read"])
            ):
                continue
            readable.append(source_kind)
        return readable

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet[PlatformAlertConfiguration]:
        canonical_team_id = self.team.parent_team_id or self.team.id
        alerts = PlatformAlert.objects.for_team(canonical_team_id, canonical=True).order_by("grouping_key")
        return (
            PlatformAlertConfiguration.objects.for_team(canonical_team_id, canonical=True)
            .filter(source_kind__in=self._readable_source_kinds())
            .prefetch_related(Prefetch("alerts", queryset=alerts))
            .order_by("-created_at", "-id")
        )
