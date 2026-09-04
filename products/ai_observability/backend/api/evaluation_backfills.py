"""API for evaluation backfills: estimate, create, list, retrieve, cancel."""

import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Any, cast

from django.conf import settings
from django.db import IntegrityError
from django.db.models import QuerySet
from django.utils import timezone

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.common import WorkflowIDReusePolicy

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.permissions import AccessControlPermission
from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle
from posthog.temporal.ai_observability.evaluation_backfill import (
    BACKFILL_WORKFLOW_NAME,
    EvaluationBackfillInputs,
    backfill_workflow_id,
)
from posthog.temporal.ai_observability.run_session_evaluation import AI_EVENTS_RETENTION_DAYS
from posthog.temporal.common.client import sync_connect

from products.ai_observability.backend.api.evaluations import EvaluationConditionSerializer
from products.ai_observability.backend.backfill_candidates import count_backfill_candidates
from products.ai_observability.backend.models.evaluation_backfill import (
    ACTIVE_BACKFILL_STATUSES,
    EvaluationBackfill,
    EvaluationBackfillStatus,
)
from products.ai_observability.backend.models.evaluations import Evaluation, EvaluationTarget

logger = structlog.get_logger(__name__)


class BackfillCountThrottle(PersonalApiKeyOrUserRateThrottle):
    """Covers session-authenticated callers, which the global burst/sustained throttles skip.

    `estimate` and `create` each run a synchronous ClickHouse count, so an ordinary UI session
    could otherwise saturate the query pool by resubmitting wide windows.
    """

    scope = "llma_eval_backfill_count"
    rate = "20/minute"


class EvaluationBackfillRequestSerializer(serializers.Serializer):
    window_start = serializers.DateTimeField(help_text="Inclusive start of the window, by unit timestamp.")
    window_end = serializers.DateTimeField(
        help_text="Exclusive end of the window. Values in the future are clamped to now."
    )
    conditions = EvaluationConditionSerializer(
        many=True,
        required=False,
        help_text="Condition sets to match. Defaults to the evaluation's own condition sets.",
    )
    rerun_existing = serializers.BooleanField(
        default=False,
        help_text="Evaluate units again even when this evaluation already has a result for them.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # No span check here: the clamp bounds the window to the retention period, so a caller who
        # asks for a wider range gets it narrowed instead of rejected.
        if attrs["window_start"] >= attrs["window_end"]:
            raise ValidationError("The start of the range must be before the end.")
        return attrs


class EvaluationBackfillEstimateSerializer(serializers.Serializer):
    total_units = serializers.IntegerField(help_text="Units that would be evaluated.")
    unit = serializers.ChoiceField(
        choices=EvaluationTarget.choices,
        help_text="What one unit is: a generation, a trace, or a session.",
    )
    window_start = serializers.DateTimeField(help_text="Window start after clamping.")
    window_end = serializers.DateTimeField(help_text="Window end after clamping.")


class EvaluationBackfillConditionSerializer(serializers.Serializer):
    """One condition set as it was frozen onto the backfill: no id, no compiled bytecode."""

    properties = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text="Property filters (event or person) that scope which units match this condition set.",
    )
    rollout_percentage = serializers.FloatField(
        required=False,
        default=100,
        help_text="Percentage (0-100) of matching units sampled for this condition set.",
    )


class EvaluationBackfillSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="User who started the backfill.")
    target = serializers.ChoiceField(
        choices=EvaluationTarget.choices,
        read_only=True,
        help_text="What one unit is, frozen at creation: a generation, a trace, or a session.",
    )
    conditions = EvaluationBackfillConditionSerializer(
        many=True,
        read_only=True,
        help_text="Condition sets frozen at creation, so an edit to the evaluation does not change this run.",
    )

    class Meta:
        model = EvaluationBackfill
        fields = [
            "id",
            "status",
            "target",
            "window_start",
            "window_end",
            "conditions",
            "rerun_existing",
            "total_count",
            "dispatched_count",
            "skipped_count",
            "created_by",
            "created_at",
            "finished_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Backfill identifier."},
            "status": {"help_text": "running while the walk is dispatching, then completed or cancelled."},
            "window_start": {"help_text": "Inclusive start of the window, by unit timestamp."},
            "window_end": {"help_text": "Exclusive end of the window."},
            "rerun_existing": {"help_text": "Whether units with an existing result are evaluated again."},
            "total_count": {"help_text": "Units matched at creation; the ceiling on dispatched_count."},
            "dispatched_count": {"help_text": "Units the backfill has started an evaluation for so far."},
            "skipped_count": {"help_text": "Units the live path had already covered, so nothing was dispatched."},
            "created_at": {"help_text": "When the backfill was created."},
            "finished_at": {"help_text": "When the backfill reached a terminal status; null while it runs."},
        }


class EvaluationBackfillViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Historical runs of one evaluation over a closed time window (nested under an evaluation)."""

    scope_object = "evaluation"
    scope_object_read_actions = ["list", "retrieve", "estimate"]
    scope_object_write_actions = ["create", "cancel"]
    permission_classes = [AccessControlPermission]
    serializer_class = EvaluationBackfillSerializer
    # `objects` is fail-closed; `safely_get_queryset` re-scopes to the request team and evaluation.
    queryset = EvaluationBackfill.objects.unscoped()

    def get_throttles(self) -> list[Any]:
        # Append, never replace: returning only this throttle would drop the global burst and
        # sustained limits from the two actions that run a ClickHouse count.
        if self.action in ("estimate", "create"):
            return [*super().get_throttles(), BackfillCountThrottle()]
        return super().get_throttles()

    def _evaluation_for_url(self) -> Evaluation:
        cached = getattr(self, "_evaluation_for_url_cache", None)
        if cached is not None:
            return cached
        try:
            evaluation_id = uuid.UUID(self.kwargs["parent_lookup_evaluation_id"])
        except (KeyError, ValueError):
            raise NotFound()
        evaluation = Evaluation.objects.filter(team_id=self.team_id, pk=evaluation_id, deleted=False).first()
        if evaluation is None:
            raise NotFound()
        self.check_object_permissions(self.request, evaluation)
        self._evaluation_for_url_cache = evaluation
        return evaluation

    def safely_get_queryset(self, queryset: QuerySet[EvaluationBackfill]) -> QuerySet[EvaluationBackfill]:
        return (
            queryset.filter(team_id=self.team_id, evaluation=self._evaluation_for_url())
            .select_related("created_by")
            .order_by("-created_at")
        )

    def _validated_request(self, request: Request) -> dict[str, Any]:
        serializer = EvaluationBackfillRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return cast(dict[str, Any], serializer.validated_data)

    def _clamped_window(self, data: dict[str, Any]) -> tuple[datetime, datetime]:
        """The requested window, bounded to the span the ai_events table can still answer for."""
        now = timezone.now()
        window_end = min(data["window_end"], now)
        window_start = max(data["window_start"], now - timedelta(days=AI_EVENTS_RETENTION_DAYS))
        if window_start >= window_end:
            raise ValidationError(
                f"The range must end in the past and start within the last {AI_EVENTS_RETENTION_DAYS} days."
            )
        return window_start, window_end

    def _conditions(self, evaluation: Evaluation, data: dict[str, Any]) -> list[dict[str, Any]]:
        """The condition sets to freeze, reduced to what the walk reads.

        An empty list is refused rather than passed on: the candidate query treats no conditions as
        no filter and would match every generation in the window, while the live scheduler evaluates
        nothing for an evaluation with no condition sets.
        """
        submitted = data.get("conditions")
        source = submitted if submitted is not None else (evaluation.conditions or [])
        if not source:
            raise ValidationError("Add at least one condition set to this backfill.")
        return [
            {
                "properties": condition.get("properties", []),
                "rollout_percentage": condition.get("rollout_percentage", 100),
            }
            for condition in source
        ]

    def _count(
        self,
        evaluation: Evaluation,
        conditions: list[dict[str, Any]],
        window_start: datetime,
        window_end: datetime,
        rerun_existing: bool,
    ) -> int:
        return count_backfill_candidates(
            team=self.team,
            evaluation_id=str(evaluation.id),
            target=evaluation.target,
            conditions=conditions,
            window_start=window_start,
            window_end=window_end,
            rerun_existing=rerun_existing,
        )

    @extend_schema(
        request=EvaluationBackfillRequestSerializer,
        responses={200: EvaluationBackfillEstimateSerializer},
    )
    @action(detail=False, methods=["post"], pagination_class=None)
    def estimate(self, request: Request, **kwargs: Any) -> Response:
        """Count what a backfill over the given window would evaluate, without creating one."""
        evaluation = self._evaluation_for_url()
        data = self._validated_request(request)
        window_start, window_end = self._clamped_window(data)
        conditions = self._conditions(evaluation, data)
        total = self._count(evaluation, conditions, window_start, window_end, data["rerun_existing"])
        response = EvaluationBackfillEstimateSerializer(
            {
                "total_units": total,
                "unit": evaluation.target,
                "window_start": window_start,
                "window_end": window_end,
            }
        )
        return Response(response.data)

    @extend_schema(
        request=EvaluationBackfillRequestSerializer,
        responses={201: EvaluationBackfillSerializer},
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        """Create a backfill: freeze the conditions, count the units, start the walk."""
        evaluation = self._evaluation_for_url()
        data = self._validated_request(request)
        window_start, window_end = self._clamped_window(data)
        if (
            EvaluationBackfill.objects.for_team(self.team_id)
            .filter(evaluation=evaluation, status__in=ACTIVE_BACKFILL_STATUSES)
            .exists()
        ):
            raise ValidationError("This evaluation already has a running backfill.")

        conditions = self._conditions(evaluation, data)
        rerun_existing = data["rerun_existing"]
        total = self._count(evaluation, conditions, window_start, window_end, rerun_existing)
        if total == 0:
            raise ValidationError(f"No {evaluation.target}s in this range match these conditions. Try a wider range.")

        try:
            backfill = EvaluationBackfill.objects.for_team(self.team_id).create(
                evaluation=evaluation,
                team=self.team,
                window_start=window_start,
                window_end=window_end,
                target=evaluation.target,
                conditions=conditions,
                rerun_existing=rerun_existing,
                total_count=total,
                created_by=cast(Any, request.user),
            )
        except IntegrityError:
            # Concurrent create lost the one-active-per-evaluation race.
            raise ValidationError("This evaluation already has a running backfill.")

        try:
            client = sync_connect()
            asyncio.run(
                client.start_workflow(
                    BACKFILL_WORKFLOW_NAME,
                    EvaluationBackfillInputs(backfill_id=str(backfill.id), team_id=self.team_id),
                    id=backfill_workflow_id(str(backfill.id)),
                    task_queue=settings.LLMA_TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                )
            )
        except Exception:
            # Nothing else creates the workflow, so a row left behind would sit at running forever
            # and block the next backfill through the one-active constraint.
            EvaluationBackfill.objects.for_team(self.team_id).filter(pk=backfill.pk).delete()
            logger.exception("llma.evaluation_backfill_start_failed", backfill_id=str(backfill.pk))
            raise APIException("Couldn't start the backfill. Try again.")

        return Response(self.get_serializer(backfill).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: EvaluationBackfillSerializer})
    @action(detail=True, methods=["post"], pagination_class=None)
    def cancel(self, request: Request, **kwargs: Any) -> Response:
        """Stop a running backfill. Evaluations already dispatched still finish."""
        backfill = self.get_object()
        finished_at = timezone.now()
        updated = (
            EvaluationBackfill.objects.for_team(self.team_id)
            .filter(pk=backfill.pk, status=EvaluationBackfillStatus.RUNNING)
            .update(status=EvaluationBackfillStatus.CANCELLED, finished_at=finished_at)
        )
        if updated:
            try:
                client = sync_connect()
                asyncio.run(client.get_workflow_handle(backfill_workflow_id(str(backfill.pk))).cancel())
            except Exception:
                # The workflow reads the row's status at every tick and stops on a terminal one.
                logger.exception("llma.evaluation_backfill_cancel_failed", backfill_id=str(backfill.pk))
            backfill.status = EvaluationBackfillStatus.CANCELLED
            backfill.finished_at = finished_at
        return Response(self.get_serializer(backfill).data)
