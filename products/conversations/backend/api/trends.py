from __future__ import annotations

from django.db.models import QuerySet

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.permissions import APIScopePermission

from products.conversations.backend.models import IncidentStatus, TicketAlertRule, TicketIncident
from products.conversations.backend.models.ticket_alert_rule import (
    MAX_ENABLED_RULES_PER_TEAM,
    MAX_RULE_WINDOW_MINUTES,
    MIN_RULE_WINDOW_MINUTES,
    MIN_SPIKE_MULTIPLIER,
)
from products.conversations.backend.ticket_filtering import (
    RULE_ALLOWED_FILTER_KEYS,
    RULE_IGNORED_FILTER_KEYS,
    validate_rule_filter_values,
)


class TicketAlertRuleSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, help_text="User who created the rule.")
    filters = serializers.DictField(
        child=serializers.CharField(help_text="Filter value in tickets-list query-param form."),
        required=False,
        default=dict,
        help_text=(
            "Ticket filters in the tickets list endpoint's query-param form, e.g. "
            '`{"channel_source": "email", "tags": "[\\"billing\\"]"}`. Matching tickets created within the '
            "rule's window count toward the threshold. Allowed keys: status, priority, channel_source, "
            "channel_detail, assignee, distinct_ids, sla, snoozed, tags, tags_all, tags_exclude, "
            "ai_triage_result. Free-text search is not supported in rules."
        ),
    )

    class Meta:
        model = TicketAlertRule
        fields = [
            "id",
            "name",
            "filters",
            "window_minutes",
            "min_count",
            "spike_multiplier",
            "enabled",
            "last_evaluated_at",
            "last_fired_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "last_evaluated_at", "last_fired_at", "created_by", "created_at", "updated_at"]
        extra_kwargs = {
            "name": {"help_text": "Display name for the rule, shown in alerts and the trends view."},
            "window_minutes": {
                "help_text": (
                    f"Evaluation window in minutes ({MIN_RULE_WINDOW_MINUTES}-{MAX_RULE_WINDOW_MINUTES}). "
                    "The rule counts matching tickets created within this trailing window. "
                    "Rules with a spike_multiplier evaluate in whole hours (the window is rounded up)."
                ),
                "min_value": MIN_RULE_WINDOW_MINUTES,
                "max_value": MAX_RULE_WINDOW_MINUTES,
            },
            "min_count": {
                "help_text": "Minimum matching tickets in the window before the rule can fire.",
                "min_value": 1,
                "max_value": 100_000,
            },
            "spike_multiplier": {
                "help_text": (
                    "When set, the rule also requires ticket volume to exceed this multiple of the rule's "
                    "historical baseline (relative spike detection). When null, the rule fires purely on "
                    "min_count within the window."
                ),
                "min_value": MIN_SPIKE_MULTIPLIER,
                "max_value": 100.0,
            },
            "enabled": {"help_text": "Disabled rules are kept but never evaluated."},
        }

    def validate_filters(self, value: dict[str, str]) -> dict[str, str]:
        unknown = set(value) - RULE_ALLOWED_FILTER_KEYS
        if unknown:
            ignored = unknown & RULE_IGNORED_FILTER_KEYS
            if ignored:
                raise serializers.ValidationError(
                    f"Time and ordering filters are not allowed in alert rules: {', '.join(sorted(ignored))}. "
                    "The rule's window supplies the time bound."
                )
            if "search" in unknown:
                raise serializers.ValidationError(
                    "Free-text search is not supported in alert rules. Use tags or the other filters instead."
                )
            raise serializers.ValidationError(f"Unknown filter keys: {', '.join(sorted(unknown))}.")
        # Value validation: a malformed value evaluates as "no filter", silently
        # broadening the rule to all tickets — reject it at save time instead.
        errors = validate_rule_filter_values(value)
        if errors:
            raise serializers.ValidationError(errors)
        return value

    def validate(self, attrs: dict) -> dict:
        will_be_enabled = attrs.get("enabled", self.instance.enabled if self.instance else True)
        if will_be_enabled:
            team = self.context["get_team"]()
            # Rows are stored under the canonical (parent) team id — count there.
            canonical_team_id = team.parent_team_id or team.id
            enabled_rules = TicketAlertRule.objects.filter(team_id=canonical_team_id, enabled=True)
            if self.instance is not None:
                enabled_rules = enabled_rules.exclude(id=self.instance.id)
            if enabled_rules.count() >= MAX_ENABLED_RULES_PER_TEAM:
                raise serializers.ValidationError(
                    {"enabled": f"A team can have at most {MAX_ENABLED_RULES_PER_TEAM} enabled alert rules."}
                )
        return attrs


class IncidentSampleTicketSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Ticket UUID.")
    ticket_number = serializers.IntegerField(read_only=True, help_text="Human-readable ticket number.")


class TicketIncidentDetailsSerializer(serializers.Serializer):
    title = serializers.CharField(
        read_only=True, required=False, help_text="Human-readable incident summary at detection time."
    )
    sample_tickets = IncidentSampleTicketSerializer(
        many=True, read_only=True, required=False, help_text="Most recent tickets that contributed to the spike."
    )
    sparkline_hourly = serializers.ListField(
        child=serializers.IntegerField(),
        read_only=True,
        required=False,
        help_text="Hourly ticket counts for the trailing 24 hours, oldest first.",
    )
    channel_mix = serializers.DictField(
        child=serializers.IntegerField(),
        read_only=True,
        required=False,
        help_text="Ticket counts by channel within the fired window (overall-volume incidents only).",
    )


class TicketIncidentSerializer(serializers.ModelSerializer):
    details = TicketIncidentDetailsSerializer(
        read_only=True, help_text="Detection snapshot: title, sample tickets, sparkline, channel mix."
    )
    rule_name = serializers.SerializerMethodField(
        help_text="Name of the alert rule that fired, for rule-scoped incidents."
    )

    class Meta:
        model = TicketIncident
        fields = [
            "id",
            "scope",
            "dimension_value",
            "rule",
            "rule_name",
            "status",
            "detected_at",
            "resolved_at",
            "window_minutes",
            "observed_count",
            "baseline_value",
            "zscore",
            "details",
            "calm_run_count",
            "created_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "scope": {"help_text": "What spiked: overall volume, a channel, a priority, or a custom alert rule."},
            "dimension_value": {
                "help_text": "Discriminator within the scope: the channel/priority value or rule id. Empty for overall volume."
            },
            "rule": {"help_text": "The alert rule that fired, for rule-scoped incidents."},
            "status": {"help_text": "Incident state: active, resolved (auto), or dismissed (by a user)."},
            "detected_at": {"help_text": "When the spike was first detected."},
            "resolved_at": {"help_text": "When the incident auto-resolved. Null while active or dismissed."},
            "window_minutes": {"help_text": "Evaluation window the spike was observed in."},
            "observed_count": {"help_text": "Tickets observed in the window at the latest evaluation."},
            "baseline_value": {
                "help_text": "Baseline (median) window count the spike was compared against. Null for absolute-only rules."
            },
            "zscore": {"help_text": "Robust z-score of the observed count against the baseline, when available."},
            "calm_run_count": {
                "help_text": "Consecutive evaluations below the calm threshold; the incident auto-resolves after several."
            },
        }

    def get_rule_name(self, incident: TicketIncident) -> str | None:
        return incident.rule.name if incident.rule else None


@extend_schema_view(
    list=extend_schema(description="List ticket alert rules for the project."),
    retrieve=extend_schema(description="Retrieve a single ticket alert rule."),
    create=extend_schema(description="Create a ticket alert rule from ticket filters and a threshold."),
    update=extend_schema(description="Update a ticket alert rule."),
    partial_update=extend_schema(description="Partially update a ticket alert rule."),
    destroy=extend_schema(description="Delete a ticket alert rule."),
)
class TicketAlertRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "ticket"
    # unscoped() at class level: the fail-closed manager has no team context at
    # import time; safely_get_queryset applies the team filter on every request.
    queryset = TicketAlertRule.objects.unscoped()
    serializer_class = TicketAlertRuleSerializer
    permission_classes = [IsAuthenticated, APIScopePermission]
    # PATCH only: full PUT would reset omitted fields (filters defaults to {}), clearing saved criteria
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        # TeamScopedRootMixin.save() canonicalizes writes to the parent team, so reads
        # must filter on the canonical id too or rows become invisible under child envs.
        canonical_team_id = self.team.parent_team_id or self.team.id
        return queryset.filter(team_id=canonical_team_id).select_related("created_by").order_by("-created_at")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        serializer.save(team_id=self.team_id, created_by=self.request.user)
        report_user_action(self.request.user, "support ticket alert rule created", team=self.team)

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        serializer.save()
        report_user_action(self.request.user, "support ticket alert rule updated", team=self.team)

    def perform_destroy(self, instance: TicketAlertRule) -> None:
        instance.delete()
        report_user_action(self.request.user, "support ticket alert rule deleted", team=self.team)


@extend_schema_view(
    list=extend_schema(
        description="List detected ticket incidents for the project, newest first.",
        parameters=[
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Filter by incident status. Accepts a single value or a comma-separated list. "
                    "Valid values: `active`, `resolved`, `dismissed`."
                ),
            ),
        ],
    ),
    retrieve=extend_schema(description="Retrieve a single ticket incident."),
)
class TicketIncidentViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "ticket"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["dismiss"]
    # unscoped() at class level: the fail-closed manager has no team context at
    # import time; safely_get_queryset applies the team filter on every request.
    queryset = TicketIncident.objects.unscoped()
    serializer_class = TicketIncidentSerializer
    permission_classes = [IsAuthenticated, APIScopePermission]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        # Same canonicalization as the rules viewset: detection writes rows under the
        # canonical (parent) team id via TeamScopedRootMixin.
        canonical_team_id = self.team.parent_team_id or self.team.id
        queryset = queryset.filter(team_id=canonical_team_id).select_related("rule")

        status_param = self.request.query_params.get("status")
        if status_param:
            valid_statuses = [status.value for status in IncidentStatus]
            statuses = [status.strip() for status in status_param.split(",") if status.strip() in valid_statuses]
            if statuses:
                queryset = queryset.filter(status__in=statuses)

        return queryset.order_by("-detected_at")

    @extend_schema(
        request=None,
        responses={200: TicketIncidentSerializer},
        description=(
            "Dismiss an active incident. Dismissal suppresses re-detection of the same "
            "scope for 24 hours. Resolved incidents are left unchanged."
        ),
    )
    @action(methods=["POST"], detail=True)
    def dismiss(self, request: Request, **kwargs) -> Response:
        incident = self.get_object()
        if incident.status == IncidentStatus.ACTIVE:
            incident.status = IncidentStatus.DISMISSED
            incident.save(update_fields=["status", "updated_at"])
            report_user_action(request.user, "support ticket incident dismissed", team=self.team)
        return Response(self.get_serializer(incident).data)
