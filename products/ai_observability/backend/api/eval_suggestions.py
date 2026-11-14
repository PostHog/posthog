import uuid
from typing import Any

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
from posthog.permissions import is_service_auth
from posthog.rate_limit import AIObservabilityBackfillEstimateSustainedThrottle, AIObservabilityBackfillEstimateThrottle

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..facade import eval_suggestions as facade
from ..facade.contracts import EvalSuggestionNotFoundError
from ..models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionDismissReason,
    EvalSuggestionKind,
    EvalSuggestionRunTrigger,
    EvalSuggestionStatus,
)
from ..models.evaluations import EvaluationTarget

NOT_FOUND_MESSAGE = "No suggestion with this id in this project."


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


class EvalSuggestionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Suggestion identifier.")
    kind = serializers.ChoiceField(
        choices=EvalSuggestionKind.choices,
        read_only=True,
        help_text=(
            "new_hog: a Hog check, measured on a sample. new_llm_judge: an LLM judge that possibly applies, "
            "with examples. fix_eval: an existing evaluation that matches nothing or gives inconsistent results."
        ),
    )
    status = serializers.ChoiceField(
        choices=EvalSuggestionStatus.choices,
        read_only=True,
        help_text="proposed until someone accepts or dismisses it.",
    )
    applies = serializers.BooleanField(
        read_only=True,
        help_text=(
            "False for a fix_eval whose evaluation is gone or changed after the run, so its patch would undo "
            "that change. Always true for other kinds."
        ),
    )
    template_key = serializers.CharField(
        read_only=True,
        help_text="Catalog template or adapted check the suggestion comes from. Empty for fix_eval.",
    )
    headline = serializers.CharField(
        read_only=True,
        help_text=(
            "The problem in the project's own terms, with the number that makes it concrete, such as "
            "'1 in 125 traces ends on a failed call'. Judges carry no rate, because only Hog checks are measured."
        ),
    )
    outcome = serializers.CharField(
        read_only=True,
        help_text="What adding the evaluation does and what it costs, in one or two plain sentences.",
    )
    reason = serializers.CharField(
        read_only=True, help_text="How the problem was measured or found, for people who want the detail."
    )
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
    rollout_percentage = serializers.FloatField(
        read_only=True, help_text="Percentage (0-100) of matching units the evaluation runs on."
    )
    measured_failure_rate = serializers.FloatField(
        read_only=True,
        allow_null=True,
        help_text="Share (0-1) of sampled traces that fail the check. Only Hog checks are measured; null otherwise.",
    )
    sample_size = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="Traces the failure rate was measured on. Null when there is no rate.",
    )
    evidence = EvalSuggestionEvidenceSerializer(
        many=True, read_only=True, help_text="Up to 5 example traces, each with a one-line reason."
    )
    estimated_weekly_runs = serializers.IntegerField(
        read_only=True, allow_null=True, help_text="Runs a week at the suggested rollout, for judges."
    )
    estimated_weekly_cost_usd = serializers.FloatField(
        read_only=True,
        allow_null=True,
        help_text="Estimated weekly cost in USD on the project's own provider key, for judges. Null when unknown.",
    )
    judge_model = serializers.CharField(
        read_only=True, help_text="Model the weekly cost assumes, for LLM judges. Empty for Hog checks and fixes."
    )
    created_evaluation = serializers.UUIDField(
        read_only=True, allow_null=True, help_text="Evaluation that accepting this suggestion created."
    )
    target_evaluation = serializers.UUIDField(
        read_only=True, allow_null=True, help_text="Evaluation a fix_eval suggestion repairs."
    )
    target_evaluation_name = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Name of the evaluation a fix_eval suggestion repairs.",
    )
    similar_evaluation = serializers.UUIDField(
        read_only=True, allow_null=True, help_text="Existing evaluation that may already cover this suggestion."
    )
    similar_evaluation_name = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Name of an existing evaluation that may already cover this suggestion.",
    )
    dismiss_reason = serializers.ChoiceField(
        choices=EvalSuggestionDismissReason.choices,
        read_only=True,
        allow_null=True,
        help_text="Reason given when the suggestion was dismissed, if any.",
    )
    created_at = serializers.DateTimeField(
        read_only=True, help_text="When the run that produced the suggestion published it."
    )


class EvalSuggestionRunSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Run identifier.")
    trigger = serializers.ChoiceField(
        choices=EvalSuggestionRunTrigger.choices,
        read_only=True,
        help_text="scheduled (weekly), first_visit, or manual.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the run started.")
    completed_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the run published its suggestions."
    )


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

    @property
    def requires_resource_level_access(self) -> bool:
        # Suggestions are not evaluation objects: the list names any evaluation and accept creates new ones, so a
        # grant on one evaluation must not open them. A fix changes one evaluation, and its edit access is enough.
        return self.action != "apply_fix"

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

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        # Every response can carry evidence sampled from traces, which the query API guards with query:read.
        level = "write" if self.action in self.scope_object_write_actions else "read"
        return [f"evaluation:{level}", "query:read"]

    def _access(self) -> UserAccessControl | None:
        """None for service credentials, which read every suggestion."""
        return None if is_service_auth(self.request) else self.user_access_control

    @staticmethod
    def _suggestion_id(pk: str) -> uuid.UUID:
        try:
            return uuid.UUID(pk)
        except ValueError:
            raise NotFound(NOT_FOUND_MESSAGE)

    @extend_schema(operation_id="evaluation_suggestions_list", responses={200: EvalSuggestionListSerializer})
    def list(self, request: Request, **kwargs: Any) -> Response:
        """The latest suggestions. Loading them records the visit, and the first visit starts a run."""
        return Response(EvalSuggestionListSerializer(facade.list_eval_suggestions(self.team, self._access())).data)

    @extend_schema(request=None, responses={200: EvalSuggestionSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        """One suggestion, whatever its status. The evaluation page reads it to show a proposed fix."""
        try:
            suggestion = facade.get_eval_suggestion(self.team, self._access(), self._suggestion_id(pk))
        except EvalSuggestionNotFoundError:
            raise NotFound(NOT_FOUND_MESSAGE)
        return Response(EvalSuggestionSerializer(suggestion).data)

    @extend_schema(request=None, responses={200: EvalSuggestionEstimateSerializer})
    @action(detail=True, methods=["get"], pagination_class=None)
    def accept_estimate(self, request: Request, pk: str, **kwargs: Any) -> Response:
        """What accepting would run on recent data, and what a judge would cost, for the confirm step."""
        try:
            estimate = facade.estimate_eval_suggestion_accept(self.team, self._access(), self._suggestion_id(pk))
        except EvalSuggestionNotFoundError:
            raise NotFound(NOT_FOUND_MESSAGE)
        return Response(EvalSuggestionEstimateSerializer(estimate).data)

    @extend_schema(request=None, responses={200: EvalSuggestionAcceptSerializer})
    @action(detail=True, methods=["post"], pagination_class=None)
    def accept(self, request: Request, pk: str, **kwargs: Any) -> Response:
        """Create the evaluation from the suggestion, enabled, and run it on recent data. Safe to repeat."""
        try:
            result = facade.accept_eval_suggestion(
                self.team, self._access(), self._suggestion_id(pk), self.get_serializer_context()
            )
        except EvalSuggestionNotFoundError:
            raise NotFound(NOT_FOUND_MESSAGE)
        self.check_object_permissions(request, result.evaluation_access)
        return Response(EvalSuggestionAcceptSerializer(result).data)

    @extend_schema(request=EvalSuggestionDismissSerializer, responses={200: EvalSuggestionSerializer})
    @action(detail=True, methods=["post"], pagination_class=None)
    def dismiss(self, request: Request, pk: str, **kwargs: Any) -> Response:
        """Hide the suggestion. The same suggestion stays hidden for 90 days."""
        suggestion_id = self._suggestion_id(pk)
        body = EvalSuggestionDismissSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            suggestion = facade.dismiss_eval_suggestion(
                self.team, self._access(), suggestion_id, reason=body.validated_data.get("reason")
            )
        except EvalSuggestionNotFoundError:
            raise NotFound(NOT_FOUND_MESSAGE)
        return Response(EvalSuggestionSerializer(suggestion).data)

    @extend_schema(request=None, responses={200: EvalSuggestionSerializer})
    @action(detail=True, methods=["post"], pagination_class=None)
    def apply_fix(self, request: Request, pk: str, **kwargs: Any) -> Response:
        """Apply a fix_eval suggestion's change to the evaluation it repairs."""
        suggestion_id = self._suggestion_id(pk)
        try:
            target = facade.eval_suggestion_fix_target(self.team, self._access(), suggestion_id)
            if target is not None:
                self.check_object_permissions(request, target)
            suggestion = facade.apply_eval_suggestion_fix(
                self.team, self._access(), suggestion_id, self.get_serializer_context()
            )
        except EvalSuggestionNotFoundError:
            raise NotFound(NOT_FOUND_MESSAGE)
        return Response(EvalSuggestionSerializer(suggestion).data)
