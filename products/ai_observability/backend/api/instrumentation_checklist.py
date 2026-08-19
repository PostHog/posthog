from typing import cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.scoping.manager import TeamScopedQuerySet
from posthog.models.user import User
from posthog.permissions import AccessControlPermission

from ..instrumentation_checklist import WINDOW_DAYS, CheckKey, CheckStatus, fetch_checklist_stats, grade_checklist
from ..models.instrumentation_checklist import AIObservabilityChecklistItemState
from .metrics import llma_track_latency

CHECK_KEYS = [key.value for key in CheckKey]
CHECK_STATUSES = [check_status.value for check_status in CheckStatus]


class InstrumentationCheckSerializer(serializers.Serializer):
    key = serializers.ChoiceField(
        choices=CHECK_KEYS,
        help_text="Identifier of the check. Stable across statuses, so a surface can key its own copy off it.",
    )
    status = serializers.ChoiceField(
        choices=CHECK_STATUSES,
        help_text=(
            "How the check graded: 'ok' when the instrumentation is present, 'warning' when it is absent, "
            "'pending' when the project has too little traffic to judge, and 'dismissed' when someone on the "
            "team marked the check as not applicable."
        ),
    )
    title = serializers.CharField(help_text="Short label for the check, the same for every status.")
    detail = serializers.CharField(
        help_text=(
            "Sentence explaining what the counts mean and, for a warning, what to send. A dismissed check keeps "
            "the sentence its counts earned."
        ),
    )
    docs_url = serializers.URLField(help_text="Documentation page covering how to send the missing instrumentation.")
    stats = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Counts this check was graded from, over the same window. Which counts appear depends on the check.",
    )


class InstrumentationChecklistSerializer(serializers.Serializer):
    window_days = serializers.IntegerField(help_text="Length in days of the event window the checks were graded over.")
    checks = InstrumentationCheckSerializer(
        many=True,
        help_text="Every check, graded. Checks are always all returned, including the ones that pass.",
    )


class InstrumentationCheckActionSerializer(serializers.Serializer):
    check = serializers.ChoiceField(choices=CHECK_KEYS, help_text="Key of the check to dismiss or restore.")


class AIObservabilityInstrumentationChecklistViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Instrumentation coverage for a project's AI events."""

    scope_object = "llm_analytics"
    # ScopeBasePermission maps only the default action names, so leaving a custom action off this list
    # gives it a null scope, which 403s every personal API key, OAuth token and MCP call while browser
    # sessions keep working. Note this replaces the default write actions rather than extending them,
    # so any future create/update/destroy has to be added here too.
    scope_object_write_actions = ["dismiss", "restore"]
    serializer_class = _FallbackSerializer
    permission_classes = [IsAuthenticated, AccessControlPermission]

    @property
    def _checklist_team_id(self) -> int:
        # RootTeamMixin.save() stores rows against the parent team, so reads and the update_or_create
        # lookup have to use that same id or a repeat dismissal would insert a duplicate.
        return self.team.parent_team_id or self.team_id

    def _states(self) -> TeamScopedQuerySet[AIObservabilityChecklistItemState]:
        return AIObservabilityChecklistItemState.objects.for_team(self._checklist_team_id, canonical=True).filter(
            scope__isnull=True
        )

    def _graded_checklist(self) -> Response:
        dismissed = self._states().filter(status=AIObservabilityChecklistItemState.Status.DISMISSED)
        checks = grade_checklist(fetch_checklist_stats(self.team), dismissed.values_list("check_key", flat=True))
        serializer = InstrumentationChecklistSerializer({"window_days": WINDOW_DAYS, "checks": checks})
        return Response(serializer.data)

    @extend_schema(
        operation_id="ai_observability_instrumentation_checklist_retrieve",
        responses={200: InstrumentationChecklistSerializer},
    )
    @llma_track_latency("llma_instrumentation_checklist_list")
    @monitor(feature=None, endpoint="llma_instrumentation_checklist_list", method="GET")
    def list(self, request: Request, **kwargs) -> Response:
        """Grade every instrumentation check for this project."""
        return self._graded_checklist()

    @validated_request(
        request_serializer=InstrumentationCheckActionSerializer,
        responses={200: OpenApiResponse(response=InstrumentationChecklistSerializer)},
    )
    @action(detail=False, methods=["post"])
    @llma_track_latency("llma_instrumentation_checklist_dismiss")
    @monitor(feature=None, endpoint="llma_instrumentation_checklist_dismiss", method="POST")
    def dismiss(self, request: ValidatedRequest, **kwargs) -> Response:
        """Mark a check as not applicable to this project."""
        self._states().update_or_create(
            team_id=self._checklist_team_id,
            check_key=request.validated_data["check"],
            scope=None,
            defaults={
                "status": AIObservabilityChecklistItemState.Status.DISMISSED,
                "updated_by": cast(User, request.user),
            },
        )
        return self._graded_checklist()

    @validated_request(
        request_serializer=InstrumentationCheckActionSerializer,
        responses={200: OpenApiResponse(response=InstrumentationChecklistSerializer)},
    )
    @action(detail=False, methods=["post"])
    @llma_track_latency("llma_instrumentation_checklist_restore")
    @monitor(feature=None, endpoint="llma_instrumentation_checklist_restore", method="POST")
    def restore(self, request: ValidatedRequest, **kwargs) -> Response:
        """Bring a dismissed check back into grading."""
        self._states().filter(check_key=request.validated_data["check"]).delete()
        return self._graded_checklist()
