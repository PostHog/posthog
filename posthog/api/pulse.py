from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from django.conf import settings
from django.db import IntegrityError
from django.db.models import Count, QuerySet

import posthoganalytics
from asgiref.sync import async_to_sync
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import PulseDigest, PulseFinding, PulseSubscription
from posthog.models.pulse import DetectionMode, PulseSubscriptionFrequency
from posthog.temporal.ai.pulse.period import period_bounds, period_key
from posthog.temporal.ai.pulse.selection import select_candidates
from posthog.temporal.ai.pulse.types import PulseScanConfig
from posthog.temporal.ai.pulse.workflow import PulseScanInputs
from posthog.temporal.common.client import async_connect

MAX_PULSE_FLAG = "max-pulse"
WATCHED_MAX_CANDIDATES = 50


class MaxPulseFeatureFlagPermission(BasePermission):
    """404 (not 403) the whole Pulse surface unless `max-pulse` is enabled for the team's org.

    A 404 hides the feature's existence from teams that don't have it, rather than
    advertising it with a 403.
    """

    def has_permission(self, request: Request, view: Any) -> bool:
        team = view.team
        org_id = str(team.organization_id)
        project_id = str(team.id)
        enabled = posthoganalytics.feature_enabled(
            MAX_PULSE_FLAG,
            str(request.user.distinct_id),
            groups={"organization": org_id, "project": project_id},
            group_properties={"organization": {"id": org_id}, "project": {"id": project_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
        if not enabled:
            raise NotFound()
        return True


class PulseFindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = PulseFinding
        fields = [
            "id",
            "digest",
            "metric_label",
            "metric_descriptor",
            "current_value",
            "baseline_value",
            "change_pct",
            "robust_z",
            "impact",
            "attribution_breakdown",
            "evidence",
            "narrative",
            "chart_thumbnail_url",
            "rank",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "digest",
            "metric_label",
            "metric_descriptor",
            "current_value",
            "baseline_value",
            "change_pct",
            "robust_z",
            "impact",
            "attribution_breakdown",
            "evidence",
            "narrative",
            "chart_thumbnail_url",
            "rank",
            "created_at",
        ]
        extra_kwargs = {
            "metric_label": {"help_text": "Human-readable name of the metric this finding is about."},
            "metric_descriptor": {"help_text": "Opaque descriptor (source, label, query) Pulse re-evaluates."},
            "current_value": {"help_text": "Metric value for the current period."},
            "baseline_value": {"help_text": "Baseline median over the configured baseline window."},
            "change_pct": {"help_text": "Fractional change vs baseline median, e.g. 0.5 means +50%."},
            "robust_z": {
                "help_text": "Robust z-score (median/MAD based). Secondary signal only, never a sole trigger."
            },
            "impact": {"help_text": "Ranking score: abs(change_pct) * sqrt(baseline_median)."},
            "attribution_breakdown": {
                "help_text": "Breakdown segment that best explains the change, e.g. {'$browser': 'Safari'}, or null."
            },
            "evidence": {
                "help_text": "Supporting evidence: {'series': [...]} recent weekly values, {'daily_series': "
                "[...]} daily values across the period for the finding chart, {'session_ids': [...]} for example "
                "replays, and/or {'references': [{type, label, timestamp, id?, change?}]} for the related changes "
                "(feature flags, experiments, annotations) the narrative tied to this finding — each timestamped "
                "so it can be placed on the finding's timeline, or null."
            },
            "narrative": {"help_text": "LLM-generated explanation of the change."},
        }


class PulseDigestSerializer(serializers.ModelSerializer):
    findings = PulseFindingSerializer(many=True, read_only=True)
    finding_count = serializers.SerializerMethodField()

    class Meta:
        model = PulseDigest
        fields = [
            "id",
            "period_start",
            "period_end",
            "status",
            "workflow_run_id",
            "error",
            "summary",
            "created_at",
            "finding_count",
            "findings",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "status": {"help_text": "Lifecycle of this scan run (pending, generating, delivered, failed)."},
            "workflow_run_id": {"help_text": "Temporal workflow run id that produced this digest."},
            "error": {"help_text": "Error payload if the scan run failed, otherwise null."},
            "summary": {"help_text": "Digest-level big-picture synthesis across findings (LLM-written, may be empty)."},
        }

    def get_finding_count(self, obj: PulseDigest) -> int:
        # Avoid extra query when prefetched, fall back to .count() otherwise.
        if hasattr(obj, "_prefetched_objects_cache") and "findings" in obj._prefetched_objects_cache:
            return len(obj._prefetched_objects_cache["findings"])
        return obj.findings.count()


class PulseDigestListSerializer(serializers.ModelSerializer):
    finding_count = serializers.IntegerField(read_only=True, help_text="Number of findings in this digest.")

    class Meta:
        model = PulseDigest
        fields = [
            "id",
            "period_start",
            "period_end",
            "status",
            "error",
            "created_at",
            "finding_count",
            "summary",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "status": {"help_text": "Lifecycle of this scan run (pending, generating, delivered, failed)."},
            "error": {"help_text": "Error payload (with a `message`) if the scan run failed, otherwise null."},
            "summary": {"help_text": "Digest-level big-picture synthesis across findings (LLM-written, may be empty)."},
        }


class PulseSubscriptionSerializer(serializers.ModelSerializer):
    min_change_pct = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
        help_text="Primary gate: minimum absolute fractional change to flag (0.0-1.0).",
    )
    baseline_weeks = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=52,
        help_text="Number of completed weeks used to compute the baseline median.",
    )
    max_findings = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=50,
        help_text="Maximum findings surfaced per digest.",
    )
    robust_z_threshold = serializers.FloatField(
        required=False,
        min_value=0.1,
        max_value=10.0,
        help_text="Secondary informational threshold for the robust z-score. Never a sole trigger.",
    )

    class Meta:
        model = PulseSubscription
        fields = [
            "id",
            "enabled",
            "frequency",
            "detection_mode",
            "sensitivity",
            "min_change_pct",
            "baseline_weeks",
            "max_findings",
            "robust_z_threshold",
            "last_scan_at",
            "next_scan_at",
            "created_at",
        ]
        read_only_fields = ["id", "last_scan_at", "next_scan_at", "created_at"]
        extra_kwargs = {
            "enabled": {"help_text": "Whether Pulse runs scans for this team."},
            "frequency": {"help_text": "Scan cadence (weekly or daily)."},
            "detection_mode": {"help_text": "Detection algorithm. Only 'change_v1' is available in v1."},
            "sensitivity": {"help_text": "Preset that derives thresholds, or 'custom' to use the raw knobs."},
            "last_scan_at": {"help_text": "When Pulse last completed a scan for this team."},
            "next_scan_at": {"help_text": "When the next scan is scheduled."},
        }

    def validate_detection_mode(self, value: str) -> str:
        if value == DetectionMode.DISCOVERY:
            raise ValidationError("detection_mode 'discovery' is not available in v1.")
        return value


class PulseWatchedCandidateSerializer(serializers.Serializer):
    """A single metric Pulse is currently watching (read-only transparency)."""

    source = serializers.CharField(
        help_text="Where the candidate came from (dashboard_tile, recent_insight, top_event)."
    )
    source_id = serializers.CharField(allow_null=True, help_text="Underlying insight/event id, if any.")
    label = serializers.CharField(help_text="Human-readable metric name.")
    query = serializers.JSONField(help_text="TrendsQuery-shaped dict Pulse re-evaluates.")


class PulseScanConfigSerializer(serializers.Serializer):
    """Per-run scan tuning knobs for a manual staff trigger.

    Every field is optional; omitted knobs fall back to the built-in defaults (the production
    constants), so a partial override is "defaults plus the knobs you set". Nothing is persisted —
    the resolved config rides along with the one-off scan that started it.
    """

    # Selection — which metrics get scanned. A per-source limit of 0 turns that source off.
    max_candidates = serializers.IntegerField(
        required=False, min_value=1, max_value=1000, help_text="Cap on total metrics scanned per run."
    )
    recent_days = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=365,
        help_text="Lookback window for recently-accessed dashboards and recently-viewed insights.",
    )
    min_viewers_for_recent_insight = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        help_text="Minimum distinct viewers for the recently-viewed-insights source to include an insight.",
    )
    dashboard_tile_limit = serializers.IntegerField(
        required=False, min_value=0, max_value=200, help_text="Max insights from pinned/recent dashboards (0 = off)."
    )
    recent_insight_limit = serializers.IntegerField(
        required=False, min_value=0, max_value=500, help_text="Max recently-viewed insights (0 = off)."
    )
    saved_insight_limit = serializers.IntegerField(
        required=False, min_value=0, max_value=200, help_text="Max recently-edited saved Trends insights (0 = off)."
    )
    top_event_limit = serializers.IntegerField(
        required=False, min_value=0, max_value=500, help_text="Max highest-volume events (0 = off)."
    )
    # Detection — what counts as a notable change.
    min_baseline_value = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1_000_000.0,
        help_text="Volume floor: skip metrics whose baseline median is below this (the top noise lever).",
    )
    min_change_pct = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=10.0,
        help_text="Primary gate: minimum absolute fractional change to flag (0.25 = 25%).",
    )
    robust_z_threshold = serializers.FloatField(
        required=False,
        min_value=0.1,
        max_value=10.0,
        help_text="Secondary informational threshold for the robust z-score. Never a sole trigger.",
    )
    baseline_weeks = serializers.IntegerField(
        required=False,
        min_value=3,
        max_value=12,
        help_text="Completed weeks used to compute the baseline median.",
    )
    max_findings = serializers.IntegerField(
        required=False, min_value=1, max_value=50, help_text="Maximum findings surfaced per digest."
    )


class PulseDigestViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated, MaxPulseFeatureFlagPermission]
    queryset = PulseDigest.objects.unscoped()

    def get_serializer_class(self):
        if self.action == "list":
            return PulseDigestListSerializer
        return PulseDigestSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        qs = queryset.filter(team_id=self.team_id).order_by("-created_at")
        if self.action == "list":
            qs = qs.annotate(finding_count=Count("findings"))
        elif self.action == "retrieve":
            qs = qs.prefetch_related("findings")
        return qs

    @extend_schema(
        request=PulseScanConfigSerializer,
        responses={202: OpenApiResponse(description="Scan triggered; returns the Temporal workflow id.")},
    )
    @action(detail=False, methods=["post"])
    def trigger_scan(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Kick off a one-off Pulse scan for this team now, without waiting for the schedule.

        Staff-only for now (404 hides it from non-staff); the gate can be relaxed to expose it to users later.

        An optional body of tuning knobs (PulseScanConfig) overrides the heuristics for this run only —
        nothing is persisted. The override is staff-gated by the same 404 as the trigger itself. With no
        body, the run resolves its detection thresholds from the team's PulseSubscription, as a scheduled
        run would.
        """
        if not request.user.is_staff:
            raise NotFound()

        config_serializer = PulseScanConfigSerializer(data=request.data or {})
        config_serializer.is_valid(raise_exception=True)
        # An empty body means "use the team's saved settings" (config=None → resolved in the workflow);
        # any provided knob produces a full override built over the built-in defaults.
        override = PulseScanConfig(**config_serializer.validated_data) if config_serializer.validated_data else None

        team = self.team
        subscription = PulseSubscription.objects.unscoped().filter(team_id=team.id).first()
        frequency = subscription.frequency if subscription else PulseSubscriptionFrequency.WEEKLY
        now = datetime.now(UTC)
        period_from, period_to = period_bounds(now, frequency)
        inputs = PulseScanInputs(
            team_id=team.id,
            period_key=period_key(now, frequency),
            period_start=period_from.isoformat(),
            period_end=period_to.isoformat(),
            user_id=request.user.id,
            config=override,
        )
        # Unique id (vs the scheduler's deterministic id) so a manual run never collides with a scheduled one.
        workflow_id = f"pulse-scan-manual-{team.id}-{uuid4()}"

        async def _start() -> None:
            client = await async_connect()
            await client.start_workflow(
                "pulse-scan",
                inputs,
                id=workflow_id,
                task_queue=settings.MAX_AI_TASK_QUEUE,
            )

        async_to_sync(_start)()
        return Response({"workflow_id": workflow_id}, status=status.HTTP_202_ACCEPTED)


class PulseFindingViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated, MaxPulseFeatureFlagPermission]
    queryset = PulseFinding.objects.unscoped()
    serializer_class = PulseFindingSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        qs = queryset.filter(digest__team_id=self.team_id)
        digest_id = self.request.query_params.get("digest")
        if digest_id:
            qs = qs.filter(digest_id=digest_id)
        return qs.order_by("rank", "-created_at")


class PulseSubscriptionViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated, MaxPulseFeatureFlagPermission]
    queryset = PulseSubscription.objects.unscoped()
    serializer_class = PulseSubscriptionSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id)

    def perform_create(self, serializer: serializers.ModelSerializer) -> None:
        # OneToOneField on team enforces singleton at DB level; the explicit pre-check
        # gives a friendly 400 in the common path but we catch IntegrityError for the
        # concurrent-POST race.
        if PulseSubscription.objects.filter(team_id=self.team_id).exists():
            raise ValidationError("This team already has a Pulse subscription. Use PATCH to update it.")
        try:
            serializer.save(team_id=self.team_id, created_by=self.request.user)
        except IntegrityError as exc:
            raise ValidationError("This team already has a Pulse subscription. Use PATCH to update it.") from exc

    @extend_schema(responses={200: OpenApiResponse(response=PulseSubscriptionSerializer)})
    @action(detail=False, methods=["get"], url_path="current")
    def current(self, request: Request, *args, **kwargs) -> Response:
        sub = PulseSubscription.objects.filter(team_id=self.team_id).first()
        if sub:
            return Response(self.get_serializer(sub).data)
        return Response(
            {
                "id": None,
                "enabled": False,
                "frequency": "weekly",
                "detection_mode": "change_v1",
                "sensitivity": "balanced",
                "min_change_pct": 0.25,
                "baseline_weeks": 4,
                "max_findings": 5,
                "robust_z_threshold": 3.5,
                "last_scan_at": None,
                "next_scan_at": None,
                "created_at": None,
            }
        )

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(response=PulseWatchedCandidateSerializer(many=True))},
    )
    @action(detail=False, methods=["get"], url_path="watched")
    def watched(self, request: Request, *args, **kwargs) -> Response:
        # Show the default watched set (the baseline selection), just capped smaller for the panel.
        candidates = async_to_sync(select_candidates)(
            team_id=self.team_id, config=PulseScanConfig(max_candidates=WATCHED_MAX_CANDIDATES)
        )
        rows = [
            {
                "source": c.descriptor.source,
                "source_id": None if c.descriptor.source_id is None else str(c.descriptor.source_id),
                "label": c.descriptor.label,
                "query": c.descriptor.query,
            }
            for c in candidates
        ]
        return Response({"results": rows})
