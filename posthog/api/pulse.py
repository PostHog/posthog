from datetime import UTC, datetime
from typing import Any

from django.db.models import Count, QuerySet

from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import PulseDigest, PulseFinding, PulseSubscription
from posthog.models.pulse import PulseChannel, PulseFindingFeedback

ALLOWED_CHANNELS = {c.value for c in PulseChannel}


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
            "z_score",
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
            "z_score",
            "attribution_breakdown",
            "narrative",
            "chart_thumbnail_url",
            "rank",
            "created_at",
        ]


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
            "delivered_to",
            "workflow_run_id",
            "error",
            "created_at",
            "finding_count",
            "findings",
        ]
        read_only_fields = fields

    def get_finding_count(self, obj: PulseDigest) -> int:
        # Avoid extra query when prefetched, fall back to .count() otherwise.
        if hasattr(obj, "_prefetched_objects_cache") and "findings" in obj._prefetched_objects_cache:
            return len(obj._prefetched_objects_cache["findings"])
        return obj.findings.count()


class PulseDigestListSerializer(serializers.ModelSerializer):
    finding_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = PulseDigest
        fields = [
            "id",
            "period_start",
            "period_end",
            "status",
            "delivered_to",
            "created_at",
            "finding_count",
        ]
        read_only_fields = fields


class PulseSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PulseSubscription
        fields = [
            "id",
            "enabled",
            "frequency",
            "enabled_channels",
            "slack_channel_id",
            "email_recipients",
            "last_scan_at",
            "next_scan_at",
            "created_at",
        ]
        read_only_fields = ["id", "last_scan_at", "next_scan_at", "created_at"]

    def validate_enabled_channels(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise ValidationError("enabled_channels must be a list")
        bad = [v for v in value if v not in ALLOWED_CHANNELS]
        if bad:
            raise ValidationError(f"Invalid channels: {bad}. Allowed: {sorted(ALLOWED_CHANNELS)}")
        return value


class PulseDigestViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]
    queryset = PulseDigest.objects.all()

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
    permission_classes = [IsAuthenticated]
    queryset = PulseFinding.objects.all()
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

    @action(detail=True, methods=["post"], url_path="feedback")
    def submit_feedback(self, request: Request, *args, **kwargs) -> Response:
        finding = self.get_object()
        action_value = request.data.get("action")
        try:
            normalized = PulseFindingFeedback(action_value)
        except ValueError:
            raise ValidationError(
                f"Invalid feedback action: {action_value!r}. "
                f"Allowed: {[c.value for c in PulseFindingFeedback]}"
            )
        finding.feedback = normalized
        finding.feedback_user = request.user
        finding.feedback_at = datetime.now(UTC)
        if normalized == PulseFindingFeedback.SNOOZED:
            snoozed_until = request.data.get("snoozed_until")
            if snoozed_until:
                try:
                    finding.snoozed_until = datetime.fromisoformat(snoozed_until.replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    raise ValidationError("snoozed_until must be an ISO datetime string")
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
    permission_classes = [IsAuthenticated]
    queryset = PulseSubscription.objects.all()
    serializer_class = PulseSubscriptionSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id)

    def perform_create(self, serializer: serializers.ModelSerializer) -> None:
        if PulseSubscription.objects.filter(team_id=self.team_id).exists():
            raise ValidationError("This team already has a Pulse subscription. Use PATCH to update it.")
        serializer.save(team_id=self.team_id, created_by=self.request.user)

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
                "enabled_channels": ["in_app"],
                "slack_channel_id": "",
                "email_recipients": [],
                "last_scan_at": None,
                "next_scan_at": None,
                "created_at": None,
            }
        )
