import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Any, Protocol, cast

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import QuerySet
from django.utils import timezone

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.service import RPCError, RPCStatusCode

from posthog.hogql.errors import BaseHogQLError

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.dataclasses import frozen
from posthog.models.user import User
from posthog.permissions import AccessControlPermission, APIScopePermission, TeamMemberAccessPermission
from posthog.rate_limit import AIObservabilityBackfillCreateThrottle, AIObservabilityBackfillEstimateThrottle
from posthog.temporal.ai_observability.evaluation_backfill import (
    BACKFILL_WORKFLOW_NAME,
    EvaluationBackfillInputs,
    backfill_workflow_id,
    cancel_backfill,
    settle_horizon,
)
from posthog.temporal.ai_observability.run_aggregate_evaluation import INGESTION_LAG_MARGIN_SECONDS
from posthog.temporal.ai_observability.run_session_evaluation import AI_EVENTS_RETENTION_DAYS
from posthog.temporal.common.client import sync_connect

from products.ai_observability.backend.api.evaluations import EvaluationConditionSerializer
from products.ai_observability.backend.backfill_candidates import count_backfill_candidates
from products.ai_observability.backend.models.evaluation_backfill import ACTIVE_BACKFILL_STATUSES, EvaluationBackfill
from products.ai_observability.backend.models.evaluations import Evaluation, EvaluationTarget

logger = structlog.get_logger(__name__)


WRITE_ACTIONS = ["create", "cancel"]

# The walk pages newest-first, so the oldest units are stamped last, hours or days after the
# window was clamped. Without headroom their verdicts age past the team's drop threshold while
# the backfill is still running, and ingestion throws them away.
BACKFILL_RETENTION_MARGIN = timedelta(days=1)

# A row this young may belong to a create that has not reached `start_workflow` yet, so Temporal
# answers NOT_FOUND for a backfill that is about to be valid. Probing it would let a concurrent
# create cancel a live run and start a second walk over the same units.
BACKFILL_START_GRACE = timedelta(minutes=2)

# The tab polls the list every ten seconds while a backfill runs, and a session-authenticated
# request passes the default throttles, so probing on every request would let one open tab, or one
# caller in a loop, set the rate of a synchronous Temporal call. A live answer stays good for a
# tick, and the release of a dead row waits at most this long.
BACKFILL_ALIVE_CACHE_SECONDS = 60


@frozen
class BackfillWindow:
    """The span a backfill covers once every bound has been applied."""

    start: datetime
    end: datetime


def _duration_label(duration: timedelta) -> str:
    minutes = duration.total_seconds() / 60
    if minutes < 60:
        value, unit = minutes, "minute"
    elif minutes < 24 * 60:
        value, unit = minutes / 60, "hour"
    else:
        value, unit = minutes / (24 * 60), "day"
    rounded = round(value, 1)
    shown = str(int(rounded)) if rounded == int(rounded) else str(rounded)
    label = f"{shown} {unit}" if shown == "1" else f"{shown} {unit}s"
    # "about" whenever the duration is not a whole number of its unit, so the message never
    # reads as an exact figure the project does not actually use.
    return label if value == int(value) else f"about {label}"


class _BackfillPermissionView(Protocol):
    action: str
    team_id: int
    kwargs: dict[str, str]


class EvaluationBackfillAccessControlPermission(AccessControlPermission):
    """Authorize writes against the parent evaluation, not the `evaluation` resource as a whole.

    The generic resource check runs before the viewset can look at the parent, so a user who was
    granted editor on this one evaluation but is a viewer on the resource would be refused before
    the object-level grant is ever read. Same shape as `EvaluationReportAccessControlPermission`.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        backfill_view = cast(_BackfillPermissionView, view)
        if backfill_view.action not in WRITE_ACTIONS:
            return super().has_permission(request, view)

        # The parent check runs for every credential, scoped tokens included. `APIScopePermission`
        # already enforced the token's scopes and `TeamMemberAccessPermission` its project
        # membership, so gating this on session auth only refused a personal API key held by a
        # user whom the resource check rejects but the object-level grant allows.
        try:
            evaluation_id = uuid.UUID(str(backfill_view.kwargs.get("parent_lookup_evaluation_id")))
        except (TypeError, ValueError):
            return False
        evaluation = Evaluation.objects.filter(team_id=backfill_view.team_id, id=evaluation_id).first()
        return evaluation is not None and self.has_object_permission(request, view, evaluation)

    def has_object_permission(self, request: Request, view: APIView, obj: object) -> bool:
        if not isinstance(obj, EvaluationBackfill | Evaluation):
            return False
        evaluation = obj.evaluation if isinstance(obj, EvaluationBackfill) else obj
        return super().has_object_permission(request, view, evaluation)


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
    scope_object_write_actions = WRITE_ACTIONS
    serializer_class = EvaluationBackfillSerializer
    # `objects` is fail-closed; `safely_get_queryset` re-scopes to the request team and evaluation.
    queryset = EvaluationBackfill.objects.unscoped()
    _evaluation_for_url_cache: Evaluation | None = None

    def dangerously_get_permissions(self) -> list[BasePermission]:
        return [
            IsAuthenticated(),
            APIScopePermission(),
            EvaluationBackfillAccessControlPermission(),
            TeamMemberAccessPermission(),
        ]

    def get_throttles(self) -> list[BaseThrottle]:
        # Append, never replace: returning only this throttle would drop the global burst and
        # sustained limits from the two actions that run a ClickHouse count.
        if self.action == "estimate":
            return [*super().get_throttles(), AIObservabilityBackfillEstimateThrottle()]
        if self.action == "create":
            return [*super().get_throttles(), AIObservabilityBackfillCreateThrottle()]
        return super().get_throttles()

    def _evaluation_for_url(self) -> Evaluation:
        if self._evaluation_for_url_cache is not None:
            return self._evaluation_for_url_cache
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

    def _clamped_window(self, evaluation: Evaluation, data: dict[str, Any]) -> BackfillWindow:
        """The requested window, bounded to the span whose verdicts can be read back."""
        now = timezone.now()
        window_end: datetime = min(data["window_end"], now)
        settle_hold = settle_horizon(evaluation.target, evaluation.target_config)
        if settle_hold:
            # A trace or session is graded over `settle_hold` from its first event, so a unit any
            # younger is still filling up. Grading it now would freeze a partial verdict, and the
            # shared workflow id would then keep the live path from ever grading it properly.
            window_end = min(window_end, now - settle_hold)
            if data["window_start"] >= window_end:
                raise ValidationError(
                    f"This evaluation grades a {evaluation.target} over "
                    f"{_duration_label(settle_hold - timedelta(seconds=INGESTION_LAG_MARGIN_SECONDS))}, so a "
                    "backfill has to end before that. Try a range that ends earlier."
                )
        window_start: datetime = max(data["window_start"], now - timedelta(days=AI_EVENTS_RETENTION_DAYS))
        if window_start >= window_end:
            raise ValidationError(
                f"The range must end in the past and start within the last {AI_EVENTS_RETENTION_DAYS} days."
            )
        # A backfilled verdict is stamped at its unit's own timestamp, so ingestion applies the
        # team's drop threshold to it like any other late event. Reaching further back would run
        # the evaluations, pay for them, and have every verdict dropped before it lands.
        drop_events_older_than: timedelta | None = self.team.drop_events_older_than
        if drop_events_older_than:
            # The label rounds to the nearest hour, so anything shorter would render as "0 hours".
            # A reach that short is not worth backfilling either way.
            reach = drop_events_older_than - BACKFILL_RETENTION_MARGIN
            if reach < timedelta(hours=1):
                raise ValidationError(
                    "Backfills are not available for this project because it drops events older than "
                    f"{_duration_label(drop_events_older_than)}."
                )
            window_start = max(window_start, now - reach)
            if window_start >= window_end:
                raise ValidationError(
                    f"Backfills on this project can only reach back {_duration_label(reach)}, "
                    "because older events are dropped. Try a more recent range."
                )
        return BackfillWindow(start=window_start, end=window_end)

    def _require_enabled(self, evaluation: Evaluation) -> None:
        # The workflow cancels a backfill whose evaluation is disabled, so starting one here would
        # burn a ClickHouse count and a workflow for a run that stops on its first tick.
        if not evaluation.enabled:
            raise ValidationError("Enable the evaluation before backfilling it.")

    def _conditions(self, evaluation: Evaluation, data: dict[str, Any]) -> list[dict[str, Any]]:
        """The condition sets to freeze, reduced to what the walk reads.

        An empty list is refused rather than passed on: the candidate query treats no conditions
        as no filter and would match every generation in the window, while the live scheduler
        evaluates nothing at all for an evaluation with no condition sets.
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
        try:
            return count_backfill_candidates(
                team=self.team,
                evaluation_id=str(evaluation.id),
                target=evaluation.target,
                settle_horizon=settle_horizon(evaluation.target, evaluation.target_config),
                conditions=conditions,
                window_start=window_start,
                window_end=window_end,
                rerun_existing=rerun_existing,
            )
        except BaseHogQLError as error:
            # A property filter HogQL cannot compile is a bad request, not a server fault. The
            # message is logged rather than returned, because it names query internals.
            logger.warning(
                "llma.evaluation_backfill_condition_rejected",
                evaluation_id=str(evaluation.id),
                error=str(error),
            )
            raise ValidationError("A condition could not be applied. Check the filters and try again.")

    @extend_schema(
        request=EvaluationBackfillRequestSerializer,
        responses={200: EvaluationBackfillEstimateSerializer},
    )
    @action(detail=False, methods=["post"], pagination_class=None)
    def estimate(self, request: Request, **kwargs: Any) -> Response:
        """Count what a backfill over the given window would evaluate, without creating one."""
        evaluation = self._evaluation_for_url()
        self._require_enabled(evaluation)
        data = self._validated_request(request)
        window = self._clamped_window(evaluation, data)
        conditions = self._conditions(evaluation, data)
        total = self._count(evaluation, conditions, window.start, window.end, data["rerun_existing"])
        response = EvaluationBackfillEstimateSerializer(
            {
                "total_units": total,
                "unit": evaluation.target,
                "window_start": window.start,
                "window_end": window.end,
            }
        )
        return Response(response.data)

    def _workflow_is_alive(self, backfill: EvaluationBackfill) -> bool:
        """Whether the row's workflow still runs, releasing the row when it does not.

        A failed workflow (an exhausted retry, a worker that never picked the run up) leaves the
        row at RUNNING, and the one-active-per-evaluation constraint then refuses every later
        backfill for that evaluation. Temporal is the authority on whether the run is really live.
        """
        if timezone.now() - backfill.created_at < BACKFILL_START_GRACE:
            return True
        cache_key = f"llma/evaluation_backfill_alive/{backfill.pk}"
        if cache.get(cache_key):
            return True
        workflow_id = backfill_workflow_id(str(backfill.pk))
        try:
            client = sync_connect()
            description = asyncio.run(client.get_workflow_handle(workflow_id).describe())
            if description.status == WorkflowExecutionStatus.RUNNING:
                cache.set(cache_key, True, BACKFILL_ALIVE_CACHE_SECONDS)
                return True
        except RPCError as error:
            # Treat an unreachable Temporal as "still running": refusing a second backfill is
            # recoverable, starting one against a live walk doubles every evaluation it runs. A
            # namespace that does not resolve answers NOT_FOUND for every workflow alike, so
            # reading that as "this run is gone" would cancel every backfill at once.
            if error.status != RPCStatusCode.NOT_FOUND or "namespace" in error.message.lower():
                logger.exception("llma.evaluation_backfill_describe_failed", backfill_id=str(backfill.pk))
                return True
        except Exception:
            logger.exception("llma.evaluation_backfill_describe_failed", backfill_id=str(backfill.pk))
            return True

        # Says which read ended someone's backfill, because nothing else records it.
        logger.warning(
            "llma.evaluation_backfill_released",
            backfill_id=str(backfill.pk),
            team_id=self.team_id,
            workflow_id=workflow_id,
        )
        cancel_backfill(self.team_id, backfill.pk)
        return False

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # The UI blocks Start while a row reads as running, so a dead workflow would hold the
        # evaluation shut until someone created another backfill. At most one row per evaluation
        # is active, so this costs one Temporal probe.
        active = self.get_queryset().filter(status__in=ACTIVE_BACKFILL_STATUSES).first()
        if active is not None:
            self._workflow_is_alive(active)
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=EvaluationBackfillRequestSerializer,
        responses={201: EvaluationBackfillSerializer},
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        """Create a backfill: freeze the conditions, count the units, start the walk."""
        evaluation = self._evaluation_for_url()
        self._require_enabled(evaluation)
        data = self._validated_request(request)
        window = self._clamped_window(evaluation, data)
        active = (
            EvaluationBackfill.objects.for_team(self.team_id)
            .filter(evaluation=evaluation, status__in=ACTIVE_BACKFILL_STATUSES)
            .first()
        )
        if active is not None and self._workflow_is_alive(active):
            raise ValidationError("This evaluation already has a running backfill.")

        conditions = self._conditions(evaluation, data)
        rerun_existing = data["rerun_existing"]
        total = self._count(evaluation, conditions, window.start, window.end, rerun_existing)
        if total == 0:
            raise ValidationError(f"No {evaluation.target}s in this range match these conditions. Try a wider range.")

        try:
            backfill = EvaluationBackfill.objects.for_team(self.team_id).create(
                evaluation=evaluation,
                team=self.team,
                window_start=window.start,
                window_end=window.end,
                target=evaluation.target,
                conditions=conditions,
                rerun_existing=rerun_existing,
                total_count=total,
                created_by=cast(User, request.user),
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
        if cancel_backfill(self.team_id, backfill.pk):
            try:
                client = sync_connect()
                asyncio.run(client.get_workflow_handle(backfill_workflow_id(str(backfill.pk))).cancel())
            except Exception as error:
                # The workflow reads the row's status at every tick and stops on a terminal one, so
                # a failed handle costs nothing and does not need a stack trace.
                logger.warning("llma.evaluation_backfill_cancel_failed", backfill_id=str(backfill.pk), error=str(error))
            # The status and finished_at were written by the update, not on this instance.
            backfill.refresh_from_db()
        return Response(self.get_serializer(backfill).data)
