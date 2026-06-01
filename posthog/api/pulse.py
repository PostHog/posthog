from datetime import UTC, datetime
from typing import Any

from django.db import IntegrityError
from django.db.models import Count, QuerySet

import posthoganalytics
from asgiref.sync import async_to_sync
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import PulseDigest, PulseFinding, PulseSubscription
from posthog.models.pulse import DetectionMode, PulseFindingFeedback
from posthog.temporal.ai.pulse.selection import select_candidates

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


class PulseFeedbackSerializer(serializers.Serializer):
    """Request body for submitting feedback on a single Pulse finding."""

    action = serializers.ChoiceField(
        choices=PulseFindingFeedback.choices,
        help_text="The feedback to record for this finding (e.g. up, down, dismissed, snoozed).",
    )
    snoozed_until = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="When the finding should resurface. Only meaningful when action is 'snoozed'.",
    )


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
            "narrative",
            "chart_thumbnail_url",
            "feedback",
            "snoozed_until",
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
            "narrative": {"help_text": "LLM-generated explanation of the change."},
            "feedback": {"help_text": "User feedback state for this finding."},
            "snoozed_until": {"help_text": "When a snoozed finding should resurface."},
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
            "created_at",
            "finding_count",
            "summary",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "status": {"help_text": "Lifecycle of this scan run (pending, generating, delivered, failed)."},
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
        feedback = self.request.query_params.get("feedback")
        if feedback:
            qs = qs.filter(feedback=feedback)
        return qs.order_by("rank", "-created_at")

    @extend_schema(
        request=PulseFeedbackSerializer,
        responses={200: OpenApiResponse(response=PulseFindingSerializer)},
    )
    @action(detail=True, methods=["post"], url_path="feedback")
    def submit_feedback(self, request: Request, *args, **kwargs) -> Response:
        finding = self.get_object()
        body = PulseFeedbackSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        normalized = body.validated_data["action"]

        finding.feedback = normalized
        finding.feedback_user = request.user
        finding.feedback_at = datetime.now(UTC)
        if normalized == PulseFindingFeedback.SNOOZED:
            finding.snoozed_until = body.validated_data.get("snoozed_until")
        finding.save(update_fields=["feedback", "feedback_user", "feedback_at", "snoozed_until"])
        return Response(self.get_serializer(finding).data)


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
        candidates = async_to_sync(select_candidates)(team_id=self.team_id, max_candidates=WATCHED_MAX_CANDIDATES)
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
