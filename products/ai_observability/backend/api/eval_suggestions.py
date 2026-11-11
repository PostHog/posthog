import uuid
from typing import Any, cast

from django.db.models import F, Q, QuerySet
from django.utils import timezone

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.documentation import PostHogAutoSchema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.permissions import is_service_auth
from posthog.rate_limit import AIObservabilityBackfillEstimateSustainedThrottle, AIObservabilityBackfillEstimateThrottle

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)

from ..eval_suggestions import accept as accept_logic
from ..eval_suggestions.client import TEAM_TIMEOUT
from ..eval_suggestions.config import is_enabled_for_organization
from ..eval_suggestions.eligibility import claim_first_visit_run, queue_first_visit_run, record_visit
from ..models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionDismissReason,
    EvalSuggestionKind,
    EvalSuggestionRun,
    EvalSuggestionRunStatus,
    EvalSuggestionStatus,
)
from ..models.evaluations import Evaluation, EvaluationTarget

logger = structlog.get_logger(__name__)

# A fix whose evaluation changed after the run read it, or that is gone, no longer applies. Saving the evaluation
# by hand is how a person acts on a fix with no patch, so the card leaves the list once they do.
STALE_FIX = Q(kind=EvalSuggestionKind.FIX_EVAL) & (
    Q(target_evaluation__isnull=True)
    | Q(target_evaluation__deleted=True)
    | Q(target_evaluation__updated_at__gt=F("run__created_at"))
)


class EvalSuggestionEvidenceSerializer(serializers.Serializer):
    trace_id = serializers.CharField(help_text="Trace that shows the problem. Open it to read the example.")
    reason = serializers.CharField(help_text="One line on what this trace shows.")


class EvalSuggestionFilterSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Event property the suggested evaluation filters on.")
    value = serializers.ListField(child=serializers.CharField(), help_text="Values that match. Any of them matches.")
    operator = serializers.CharField(help_text="Property filter operator, such as 'exact'.")
    type = serializers.CharField(help_text="Property filter type, such as 'event'.")


@extend_schema_field(OpenApiTypes.OBJECT)
class EvalSuggestionDraftField(serializers.JSONField):
    pass


class EvalSuggestionSerializer(serializers.ModelSerializer):
    draft = EvalSuggestionDraftField(
        read_only=True,
        help_text=(
            "For new_hog and new_llm_judge: the evaluation create input (name, description, evaluation_type, "
            "evaluation_config, output_type, output_config, target), without conditions, which accept builds from "
            "`filters` and `rollout_percentage`. For fix_eval: the update body apply_fix applies to the target "
            "evaluation, or {} when the evaluation needs a manual fix."
        ),
    )
    filters = EvalSuggestionFilterSerializer(
        many=True,
        read_only=True,
        help_text="Property filters the suggested evaluation runs on. Empty means all AI traffic.",
    )
    evidence = EvalSuggestionEvidenceSerializer(
        many=True, read_only=True, help_text="Up to 5 example traces, each with a one-line reason."
    )
    target_evaluation_name = serializers.CharField(
        source="target_evaluation.name",
        read_only=True,
        allow_null=True,
        default=None,
        help_text="Name of the evaluation a fix_eval suggestion repairs.",
    )
    similar_evaluation_name = serializers.CharField(
        source="similar_evaluation.name",
        read_only=True,
        allow_null=True,
        default=None,
        help_text="Name of an existing evaluation that may already cover this suggestion.",
    )

    applies = serializers.SerializerMethodField(
        help_text=(
            "False for a fix_eval whose evaluation is gone or changed after the run, so its patch would undo "
            "that change. Always true for other kinds."
        )
    )

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_applies(self, suggestion: EvalSuggestion) -> bool:
        if suggestion.kind != EvalSuggestionKind.FIX_EVAL:
            return True
        target = suggestion.target_evaluation
        # The same rule as STALE_FIX, which hides these from the list.
        return target is not None and not target.deleted and target.updated_at <= suggestion.run.created_at

    class Meta:
        model = EvalSuggestion
        fields = [
            "id",
            "kind",
            "status",
            "applies",
            "template_key",
            "headline",
            "outcome",
            "reason",
            "draft",
            "filters",
            "rollout_percentage",
            "measured_failure_rate",
            "sample_size",
            "evidence",
            "estimated_weekly_runs",
            "estimated_weekly_cost_usd",
            "judge_model",
            "created_evaluation",
            "target_evaluation",
            "target_evaluation_name",
            "similar_evaluation",
            "similar_evaluation_name",
            "dismiss_reason",
            "created_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Suggestion identifier."},
            "kind": {
                "help_text": (
                    "new_hog: a Hog check, measured on a sample. new_llm_judge: an LLM judge that possibly applies, "
                    "with examples. fix_eval: an existing evaluation that matches nothing or gives inconsistent results."
                )
            },
            "status": {"help_text": "proposed until someone accepts or dismisses it."},
            "template_key": {
                "help_text": "Catalog template or adapted check the suggestion comes from. Empty for fix_eval."
            },
            "headline": {
                "help_text": (
                    "The problem in the project's own terms, with the number that makes it concrete, such as "
                    "'1 in 125 traces ends on a failed call'. Judges carry no rate, because only Hog checks are measured."
                )
            },
            "outcome": {
                "help_text": "What adding the evaluation does and what it costs, in one or two plain sentences."
            },
            "reason": {"help_text": "How the problem was measured or found, for people who want the detail."},
            "rollout_percentage": {"help_text": "Percentage (0-100) of matching units the evaluation runs on."},
            "measured_failure_rate": {
                "help_text": "Share (0-1) of sampled traces that fail the check. Only Hog checks are measured; null otherwise."
            },
            "sample_size": {"help_text": "Traces the failure rate was measured on. Null when there is no rate."},
            "estimated_weekly_runs": {"help_text": "Runs a week at the suggested rollout, for judges."},
            "estimated_weekly_cost_usd": {
                "help_text": "Estimated weekly cost in USD on the project's own provider key, for judges. Null when unknown."
            },
            "judge_model": {
                "help_text": "Model the weekly cost assumes, for LLM judges. Empty for Hog checks and fixes."
            },
            "created_evaluation": {"help_text": "Evaluation that accepting this suggestion created."},
            "target_evaluation": {"help_text": "Evaluation a fix_eval suggestion repairs."},
            "similar_evaluation": {"help_text": "Existing evaluation that may already cover this suggestion."},
            "dismiss_reason": {"help_text": "Reason given when the suggestion was dismissed, if any."},
            "created_at": {"help_text": "When the run that produced the suggestion published it."},
        }


class EvalSuggestionRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvalSuggestionRun
        fields = ["id", "trigger", "created_at", "completed_at"]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Run identifier."},
            "trigger": {"help_text": "scheduled (weekly), first_visit, or manual."},
            "created_at": {"help_text": "When the run started."},
            "completed_at": {"help_text": "When the run published its suggestions."},
        }


class EvalSuggestionListSerializer(serializers.Serializer):
    run = EvalSuggestionRunSerializer(
        allow_null=True,
        help_text="The latest completed run, which the suggestions come from. Null before the first one.",
    )
    pending = serializers.BooleanField(help_text="True while a run for this project is in progress.")
    results = EvalSuggestionSerializer(
        many=True, help_text="Open suggestions of the latest run, best first. At most 3."
    )


class EvalSuggestionDismissSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(
        choices=EvalSuggestionDismissReason.choices,
        required=False,
        allow_null=True,
        help_text="Optional reason: not_relevant, already_covered, too_noisy, or fixed_cause.",
    )


class EvalSuggestionAcceptSerializer(serializers.Serializer):
    suggestion = EvalSuggestionSerializer(help_text="The accepted suggestion.")
    evaluation_id = serializers.UUIDField(help_text="The evaluation the suggestion created, enabled.")
    backfill_id = serializers.UUIDField(
        allow_null=True,
        help_text="Backfill that runs the new evaluation on recent data. Null when recent data holds no matching unit.",
    )
    backfill_units = serializers.IntegerField(
        allow_null=True, help_text="Units the backfill evaluates: at most 500 for a Hog check and 50 for a judge."
    )


class EvalSuggestionEstimateSerializer(serializers.Serializer):
    target = serializers.ChoiceField(
        choices=EvaluationTarget.choices, help_text="What one unit is: a generation, a trace, or a session."
    )
    units = serializers.IntegerField(help_text="Units accept would evaluate on recent data.")
    window_start = serializers.DateTimeField(allow_null=True, help_text="Start of the recent window accept covers.")
    window_end = serializers.DateTimeField(allow_null=True, help_text="End of the recent window accept covers.")
    judge_model = serializers.CharField(
        allow_null=True,
        help_text="Model a judge runs on: the default for the project's active key. Null for Hog checks.",
    )
    estimated_cost_usd = serializers.FloatField(
        allow_null=True,
        help_text=(
            "units x input tokens one judge run reads x the input price of the model accept uses, in USD. "
            "0 for Hog checks, null when the price or token count is unknown."
        ),
    )


class _EnvelopeSchema(PostHogAutoSchema):
    """Prevents drf-spectacular from wrapping the ``list`` response in an array: it is one envelope object."""

    def _is_list_view(self, serializer: object = None) -> bool:
        return False


class EvalSuggestionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Up to three evaluation suggestions for the project, refreshed every week."""

    schema = _EnvelopeSchema()
    scope_object = "evaluation"
    scope_object_read_actions = ["list", "retrieve", "accept_estimate"]
    scope_object_write_actions = ["accept", "dismiss", "apply_fix"]
    # Suggestions are not evaluation objects: the list names any evaluation and accept creates new ones,
    # so a grant on one evaluation must not open them. Fixes also check the evaluation they change.
    requires_resource_level_access = True
    # `objects` is fail-closed; every action reads through `for_team` with the request team.
    queryset = EvalSuggestion.objects.unscoped()
    serializer_class = EvalSuggestionSerializer

    def get_throttles(self) -> list[BaseThrottle]:
        # The estimate runs the same ClickHouse counts as a backfill estimate, so it shares its limits.
        if self.action == "accept_estimate":
            return [
                *super().get_throttles(),
                AIObservabilityBackfillEstimateThrottle(),
                AIObservabilityBackfillEstimateSustainedThrottle(),
            ]
        return super().get_throttles()

    def _suggestions(self) -> QuerySet[EvalSuggestion]:
        """The team's suggestions, without those that name an evaluation the user cannot read."""
        suggestions = EvalSuggestion.objects.for_team(self.team_id)
        if is_service_auth(self.request):
            return suggestions
        # Runs read every event property as the project, and a card's filters, headline and evidence can carry
        # any of them, so a member with a hidden event property sees no suggestions rather than a masked one.
        restrictions = get_restricted_properties_with_group_type_index_for_team(
            user=cast(User, self.request.user), team_id=self.team_id
        )
        if split_restricted_property_names(restrictions).event:
            return suggestions.none()
        visible = self.user_access_control.filter_queryset_by_access_level(
            Evaluation.objects.filter(team_id=self.team_id)
        ).values("id")
        return suggestions.filter(
            Q(target_evaluation__isnull=True) | Q(target_evaluation_id__in=visible),
            Q(similar_evaluation__isnull=True) | Q(similar_evaluation_id__in=visible),
            Q(created_evaluation__isnull=True) | Q(created_evaluation_id__in=visible),
        )

    def _suggestion(self, pk: str) -> EvalSuggestion:
        try:
            suggestion_id = uuid.UUID(pk)
        except ValueError:
            raise NotFound("No suggestion with this id in this project.")
        suggestion = (
            self._suggestions()
            .select_related("target_evaluation", "similar_evaluation")
            .filter(id=suggestion_id)
            .first()
        )
        if suggestion is None:
            raise NotFound("No suggestion with this id in this project.")
        return suggestion

    @extend_schema(operation_id="evaluation_suggestions_list", responses={200: EvalSuggestionListSerializer})
    def list(self, request: Request, **kwargs: Any) -> Response:
        """The latest suggestions. Loading them records the visit, and the first visit starts a run."""
        if not is_enabled_for_organization(str(self.team.organization_id)):
            return Response(EvalSuggestionListSerializer({"run": None, "pending": False, "results": []}).data)
        record_visit(self.team)
        runs = EvalSuggestionRun.objects.for_team(self.team_id)
        latest = runs.filter(status=EvalSuggestionRunStatus.COMPLETED).order_by("-completed_at").first()
        pending = runs.filter(
            status=EvalSuggestionRunStatus.RUNNING, created_at__gte=timezone.now() - TEAM_TIMEOUT
        ).exists()
        if latest is None and not pending and claim_first_visit_run(self.team):
            try:
                queue_first_visit_run(self.team)
                pending = True
            except Exception:
                # The list still answers. The claim holds for the day, so the next day's visit tries again.
                logger.exception("llma.eval_suggestions_first_visit_start_failed", team_id=self.team_id)
        results = (
            self._suggestions()
            .filter(run=latest, status=EvalSuggestionStatus.PROPOSED)
            .exclude(STALE_FIX)
            .select_related("target_evaluation", "similar_evaluation")
            .order_by("-score")
            if latest
            else EvalSuggestion.objects.none()
        )
        return Response(
            EvalSuggestionListSerializer({"run": latest, "pending": pending, "results": list(results)}).data
        )

    @extend_schema(request=None, responses={200: EvalSuggestionSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        """One suggestion, whatever its status. The evaluation page reads it to show a proposed fix."""
        return Response(EvalSuggestionSerializer(self._suggestion(pk)).data)

    @extend_schema(request=None, responses={200: EvalSuggestionEstimateSerializer})
    @action(detail=True, methods=["get"], pagination_class=None)
    def accept_estimate(self, request: Request, pk: str, **kwargs: Any) -> Response:
        """What accepting would run on recent data, and what a judge would cost, for the confirm step."""
        estimate = accept_logic.estimate(self._suggestion(pk), self.team)
        return Response(
            EvalSuggestionEstimateSerializer(
                {
                    "target": estimate.target,
                    "units": estimate.units,
                    "window_start": estimate.window_start,
                    "window_end": estimate.window_end,
                    "judge_model": estimate.judge_model,
                    "estimated_cost_usd": estimate.estimated_cost_usd,
                }
            ).data
        )

    @extend_schema(request=None, responses={200: EvalSuggestionAcceptSerializer})
    @action(detail=True, methods=["post"], pagination_class=None)
    def accept(self, request: Request, pk: str, **kwargs: Any) -> Response:
        """Create the evaluation from the suggestion, enabled, and run it on recent data. Safe to repeat."""
        self._suggestion(pk)
        result = accept_logic.accept(
            pk, team=self.team, request=request, serializer_context=self.get_serializer_context()
        )
        # A repeat returns the evaluation the first accept created, which can have been restricted since.
        self.check_object_permissions(request, result.evaluation)
        return Response(
            EvalSuggestionAcceptSerializer(
                {
                    "suggestion": result.suggestion,
                    "evaluation_id": result.evaluation.id,
                    "backfill_id": result.backfill.id if result.backfill else None,
                    "backfill_units": result.backfill.total_count if result.backfill else None,
                }
            ).data
        )

    @extend_schema(request=EvalSuggestionDismissSerializer, responses={200: EvalSuggestionSerializer})
    @action(detail=True, methods=["post"], pagination_class=None)
    def dismiss(self, request: Request, pk: str, **kwargs: Any) -> Response:
        """Hide the suggestion. The same suggestion stays hidden for 90 days."""
        self._suggestion(pk)
        body = EvalSuggestionDismissSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        suggestion = accept_logic.dismiss(pk, team=self.team, reason=body.validated_data.get("reason"))
        return Response(EvalSuggestionSerializer(suggestion).data)

    @extend_schema(request=None, responses={200: EvalSuggestionSerializer})
    @action(detail=True, methods=["post"], pagination_class=None)
    def apply_fix(self, request: Request, pk: str, **kwargs: Any) -> Response:
        """Apply a fix_eval suggestion's change to the evaluation it repairs."""
        target = self._suggestion(pk).target_evaluation
        if target is not None:
            self.check_object_permissions(request, target)
        suggestion = accept_logic.apply_fix(pk, team=self.team, serializer_context=self.get_serializer_context())
        return Response(EvalSuggestionSerializer(self._suggestion(str(suggestion.id))).data)
