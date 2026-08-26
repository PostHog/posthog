"""
DRF views for autoresearch.

Responsibilities:
- Validate incoming JSON (via serializers)
- Call facade functions
- Convert contracts to JSON responses

No business logic here — that lives behind ``facade/api.py``.
"""

from dataclasses import fields
from typing import Any, cast

import structlog
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.fields import empty
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.documentation import PostHogAutoSchema
from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User

from products.autoresearch.backend.facade import api
from products.autoresearch.backend.facade.access import has_autoresearch_access
from products.autoresearch.backend.facade.contracts import AutoresearchConflict, PipelineNotFound, TrainingRunNotFound

from .serializers import (
    AutoresearchIterationSerializer,
    AutoresearchModelSerializer,
    AutoresearchPipelineCreateSerializer,
    AutoresearchPipelineSerializer,
    AutoresearchRunSerializer,
    AutoresearchTrainingRunSerializer,
    CompleteTrainingRunSerializer,
    OpenTrainingRunSerializer,
    RecordIterationSerializer,
    ResolvedTemplateSerializer,
    ResolveTemplateRequestSerializer,
    TemplateInfoSerializer,
    TrainingRunHistorySerializer,
    ValidatePipelineRequestSerializer,
    ValidatePipelineResponseSerializer,
    resolve_target,
)

logger = structlog.get_logger(__name__)


class FacadePathParamSchema(PostHogAutoSchema):
    """Types a facade-backed viewset's UUID path parameters.

    drf-spectacular reads a path parameter's type off the viewset's ``queryset`` model. These
    viewsets reach their data through the facade and declare no queryset, so each id is spelled
    out here instead. Declaring them through ``@extend_schema`` would not work: that appends the
    parameter to every operation in the viewset, including the collection routes whose path has
    no id in it. This hook only ever sees variables the path actually contains.
    """

    def _resolve_path_parameters(self, variables: Any) -> Any:
        declared = getattr(self.view, "uuid_path_parameters", {})
        resolved = []
        for parameter in super()._resolve_path_parameters(variables):
            description = declared.get(parameter["name"])
            if parameter["name"] not in declared:
                resolved.append(parameter)
                continue
            # Rebuilt rather than mutated, so the keys keep the order drf-spectacular emits.
            rebuilt: dict[str, Any] = {}
            for key, value in parameter.items():
                if key == "schema":
                    rebuilt["schema"] = {"type": "string", "format": "uuid"}
                    if description:
                        rebuilt["description"] = description
                elif key == "description" and description:
                    continue
                else:
                    rebuilt[key] = value
            resolved.append(rebuilt)
        return resolved


class AutoresearchAccessPermission(BasePermission):
    """Gate the autoresearch product behind the `autoresearch` feature flag."""

    message = "Autoresearch is not enabled for this team."

    def has_permission(self, request: Request, view: APIView) -> bool:
        team_id = getattr(view, "team_id", None)
        return has_autoresearch_access(request.user, team_id=team_id)


class _FacadePaginationMixin:
    # Drives the standard ``LimitOffsetPagination`` envelope from a facade ``(page, count)``
    # result. The facade does the slicing, so the paginator's state is set directly rather than
    # handed a queryset — keeping the param names, default page size, and ``count`` / ``next`` /
    # ``previous`` shape identical to the model-backed viewsets.
    def _paginate_via_facade(self, request: Request, fetch: Any, serializer_class: Any) -> Response:
        paginator = self.paginator  # type: ignore[attr-defined]
        limit = paginator.get_limit(request)
        offset = paginator.get_offset(request)
        page, count = fetch(offset=offset, limit=limit)
        paginator.request = request
        paginator.limit = limit
        paginator.offset = offset
        paginator.count = count
        serializer = serializer_class(instance=page, many=True)
        return paginator.get_paginated_response(serializer.data)


def _parent_pipeline_id(view: Any) -> str | None:
    """The pipeline this nested route is scoped to, or None on the unscoped collection route."""
    pipeline_id = view.kwargs.get("parent_lookup_pipeline_id")
    return str(pipeline_id) if pipeline_id else None


def _require_parent_pipeline_id(view: Any) -> str:
    """The pipeline id for a route that cannot act without one."""
    pipeline_id = _parent_pipeline_id(view)
    if pipeline_id is None:
        raise ValidationError("Pipeline not found.")
    return pipeline_id


def _pipeline_write_fields(validated: Any) -> dict[str, Any]:
    """The fields to persist.

    ``validated`` is the write contract, where a field the request body did not carry is left as
    the ``empty`` sentinel. Skipping those is what stops a PATCH writing a default over a field
    the caller never mentioned; the values ``validate()`` derived are real, so they carry through.
    """
    return {
        f.name: getattr(validated, f.name) for f in fields(validated) if getattr(validated, f.name, empty) is not empty
    }


@extend_schema(tags=["autoresearch"])
class AutoresearchPipelineViewSet(TeamAndOrgViewSetMixin, _FacadePaginationMixin, viewsets.ModelViewSet):
    """
    Manage autoresearch prediction pipelines.

    A pipeline defines a target event, population, and horizon. The autoresearch
    training loop finds the best predictive recipe; the inference workflow scores
    users daily and emits autoresearch_prediction events.
    """

    schema = FacadePathParamSchema()
    uuid_path_parameters = {"id": "A UUID string identifying this autoresearch pipeline."}
    scope_object = "autoresearch"
    scope_object_read_actions = ["list", "retrieve", "validate_definition", "list_templates", "resolve_template"]
    scope_object_write_actions = ["create", "update", "partial_update", "destroy"]
    permission_classes = [AutoresearchAccessPermission]
    serializer_class = AutoresearchPipelineSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    def get_serializer_class(self) -> type[AutoresearchPipelineSerializer | AutoresearchPipelineCreateSerializer]:
        if self.action in ("create", "partial_update", "update"):
            return AutoresearchPipelineCreateSerializer
        return AutoresearchPipelineSerializer

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_pipelines(self.team_id, offset=offset, limit=limit),
            AutoresearchPipelineSerializer,
        )

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            pipeline = api.get_pipeline(self.team_id, self.kwargs["pk"])
        except PipelineNotFound:
            raise NotFound("Pipeline not found.")
        return Response(AutoresearchPipelineSerializer(instance=pipeline).data)

    @extend_schema(
        request=AutoresearchPipelineCreateSerializer,
        # `create` responds with the read serializer, not the write one. Without this,
        # drf-spectacular infers the response from `get_serializer_class()` and the
        # generated client loses `id` — which `enrich_url: '{id}'` needs.
        responses={201: AutoresearchPipelineSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AutoresearchPipelineCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        pipeline = api.create_pipeline(
            self.team_id,
            fields=_pipeline_write_fields(serializer.validated_data),
            created_by=cast(User, request.user),
        )
        output = AutoresearchPipelineSerializer(instance=pipeline)
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=201, headers=headers)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        context = {**self.get_serializer_context(), "pipeline_id": self.kwargs["pk"]}
        serializer = AutoresearchPipelineCreateSerializer(data=request.data, partial=partial, context=context)
        serializer.is_valid(raise_exception=True)
        try:
            pipeline = api.update_pipeline(
                self.team_id,
                self.kwargs["pk"],
                fields=_pipeline_write_fields(serializer.validated_data),
            )
        except PipelineNotFound:
            raise NotFound("Pipeline not found.")
        return Response(AutoresearchPipelineSerializer(instance=pipeline).data)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            api.delete_pipeline(self.team_id, self.kwargs["pk"])
        except PipelineNotFound:
            raise NotFound("Pipeline not found.")
        return Response(status=204)

    @extend_schema(
        responses={200: TemplateInfoSerializer(many=True)},
        summary="List available templates",
        description=(
            "Return all built-in autoresearch prediction templates. "
            "Each entry describes what the template predicts, its default horizon and prediction mode, "
            "and whether it requires you to supply a target_event. "
            "After choosing a template, call autoresearch-resolve-template-create to get a fully "
            "resolved pipeline config ready to pass to autoresearch-create."
        ),
    )
    @action(detail=False, methods=["get"], url_path="templates")
    def list_templates(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(TemplateInfoSerializer(instance=api.list_templates(), many=True).data)

    @validated_request(
        request_serializer=ResolveTemplateRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=ResolvedTemplateSerializer,
                description=(
                    "Resolved pipeline config. Pass target_event, horizon_days, "
                    "training_population, inference_population, and output_person_property directly "
                    "to autoresearch-create. Always run autoresearch-validate-create on the resolved "
                    "config before creating."
                ),
            ),
            400: OpenApiResponse(
                description="Unknown template key or missing required target_event override.",
            ),
        },
        summary="Resolve a template",
        description=(
            "Resolve a template key and optional overrides into a concrete pipeline config. "
            "For activity-based templates ('likely_active_soon', 'at_risk_of_inactivity', "
            "'return_after_first_use'), the target event is auto-resolved from your event schema — "
            "check resolved_activity_event and activity_event_alternatives, then override if needed. "
            "For 'feature_adoption' and 'repeat_key_behavior', supply target_event. "
            "After resolving, call autoresearch-validate-create to check volume and warnings, "
            "then autoresearch-create to create the pipeline."
        ),
    )
    @action(detail=False, methods=["post"], url_path="resolve-template")
    def resolve_template(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = request.validated_data
        try:
            resolved = api.resolve_template(
                self.team_id,
                template_key=data["template_key"],
                target_event_override=data.get("target_event"),
                horizon_days_override=data.get("horizon_days"),
            )
        except AutoresearchConflict as exc:
            raise ValidationError(str(exc)) from exc
        return Response(ResolvedTemplateSerializer(instance=resolved).data)

    @validated_request(
        request_serializer=ValidatePipelineRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=ValidatePipelineResponseSerializer,
                description="Validation result with volume estimates, base rate, and warnings.",
            ),
        },
        summary="Validate a pipeline definition",
        description=(
            "Validate a proposed pipeline's target event and population before creating it. "
            "Returns volume estimates, base rate, and any warnings. "
            "Warnings with severity='error' must be resolved before creation can proceed. "
            "Call this before autoresearch-create."
        ),
    )
    @action(detail=False, methods=["post"], url_path="validate")
    def validate_definition(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = request.validated_data
        target_event, target_definition = resolve_target(
            team=self.team,
            target_event=data.get("target_event", ""),
            target_definition=data.get("target_definition"),
        )
        result = api.validate_definition(
            self.team_id,
            target_event=target_event,
            target_definition=target_definition,
            horizon_days=data.get("horizon_days", 7),
            training_lookback_days=data.get("training_lookback_days", 180),
            training_population=data.get("training_population", {}),
            inference_population=data.get("inference_population", {}),
        )
        return Response(ValidatePipelineResponseSerializer(instance=result).data)


@extend_schema(tags=["autoresearch"])
class AutoresearchModelViewSet(TeamAndOrgViewSetMixin, _FacadePaginationMixin, viewsets.ReadOnlyModelViewSet):
    """
    List and retrieve champion/challenger models for a pipeline.

    Models are the persisted artifacts produced by training runs. Each model
    holds a portable recipe (feature SQL, transforms, model class, params) that
    the daily inference workflow compiles to score users.
    """

    schema = FacadePathParamSchema()
    uuid_path_parameters = {"id": "A UUID string identifying this autoresearch model.", "pipeline_id": None}
    scope_object = "autoresearch"
    permission_classes = [AutoresearchAccessPermission]
    serializer_class = AutoresearchModelSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    def _should_skip_parents_filter(self) -> bool:
        return True

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_models(
                self.team_id, pipeline_id=_parent_pipeline_id(self), offset=offset, limit=limit
            ),
            AutoresearchModelSerializer,
        )

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        model = api.get_model(self.team_id, self.kwargs["pk"])
        if model is None:
            raise NotFound("Model not found.")
        return Response(AutoresearchModelSerializer(instance=model).data)


@extend_schema(tags=["autoresearch"])
class AutoresearchRunViewSet(TeamAndOrgViewSetMixin, _FacadePaginationMixin, viewsets.ReadOnlyModelViewSet):
    """
    List and retrieve inference and validation runs for a pipeline.
    """

    schema = FacadePathParamSchema()
    uuid_path_parameters = {"id": "A UUID string identifying this autoresearch run.", "pipeline_id": None}
    scope_object = "autoresearch"
    permission_classes = [AutoresearchAccessPermission]
    serializer_class = AutoresearchRunSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    def _should_skip_parents_filter(self) -> bool:
        return True

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_runs(
                self.team_id, pipeline_id=_parent_pipeline_id(self), offset=offset, limit=limit
            ),
            AutoresearchRunSerializer,
        )

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        run = api.get_run(self.team_id, self.kwargs["pk"])
        if run is None:
            raise NotFound("Run not found.")
        return Response(AutoresearchRunSerializer(instance=run).data)


@extend_schema(tags=["autoresearch"])
class AutoresearchTrainingRunViewSet(TeamAndOrgViewSetMixin, _FacadePaginationMixin, viewsets.ModelViewSet):
    """
    List, retrieve, open, record iterations into, and complete training runs for a pipeline.

    The write endpoints let an external (bring-your-own) agent or a scheduled job drive a
    training run directly — recording each iteration as it completes rather than via a single
    terminal sandbox output. Recipe validation and champion promotion stay server-side.
    """

    schema = FacadePathParamSchema()
    uuid_path_parameters = {"id": "A UUID string identifying this autoresearch training run.", "pipeline_id": None}
    scope_object = "autoresearch"
    scope_object_read_actions = ["list", "retrieve", "history"]
    scope_object_write_actions = ["create", "record_iteration", "complete"]
    permission_classes = [AutoresearchAccessPermission]
    serializer_class = AutoresearchTrainingRunSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only
    # A training run is opened and appended to, never edited or deleted — same surface the
    # CreateModelMixin + ReadOnlyModelViewSet pairing exposed before the facade move.
    http_method_names = ["get", "post", "head", "options"]

    def _should_skip_parents_filter(self) -> bool:
        return True

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_training_runs(
                self.team_id, pipeline_id=_parent_pipeline_id(self), offset=offset, limit=limit
            ),
            AutoresearchTrainingRunSerializer,
        )

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        training_run = api.get_training_run(self.team_id, self.kwargs["pk"])
        if training_run is None:
            raise NotFound("Training run not found.")
        return Response(AutoresearchTrainingRunSerializer(instance=training_run).data)

    @validated_request(
        request_serializer=OpenTrainingRunSerializer,
        responses={
            201: OpenApiResponse(
                response=AutoresearchTrainingRunSerializer,
                description="The opened training run. Record iterations against its id, then call complete.",
            ),
            400: OpenApiResponse(description="Pipeline is archived."),
        },
        summary="Open a training run",
        description=(
            "Open a new training run for a pipeline and return its id. An agent — the in-house sandbox, an "
            "external bring-your-own agent, or a scheduled job — then records iterations against this run "
            "and finalizes it with the complete endpoint. The run starts in 'running'."
        ),
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            training_run = api.open_training_run(
                self.team_id,
                _require_parent_pipeline_id(self),
                iteration_budget=request.validated_data.get("iteration_budget"),
            )
        except (PipelineNotFound, AutoresearchConflict) as exc:
            raise ValidationError(str(exc)) from exc
        return Response(AutoresearchTrainingRunSerializer(instance=training_run).data, status=201)

    @validated_request(
        request_serializer=RecordIterationSerializer,
        responses={
            201: OpenApiResponse(
                response=AutoresearchIterationSerializer,
                description="The recorded iteration.",
            ),
            400: OpenApiResponse(
                description="Recipe failed validation (e.g. disallowed model_class) or run not running."
            ),
        },
        summary="Record a training iteration",
        description=(
            "Record one iteration of an open training run. Idempotent on iteration_number — re-sending the "
            "same number updates that iteration. The recipe is validated server-side: model_class must be in "
            "the allowlist and feature_sql must be a read-only SELECT keyed on person_id."
        ),
    )
    @action(detail=True, methods=["post"], url_path="iterations")
    def record_iteration(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            iteration = api.record_iteration(self.team_id, self.kwargs["pk"], fields=dict(request.validated_data))
        except TrainingRunNotFound:
            raise NotFound("Training run not found.")
        except AutoresearchConflict as exc:
            raise ValidationError(str(exc)) from exc
        return Response(AutoresearchIterationSerializer(instance=iteration).data, status=201)

    @validated_request(
        request_serializer=CompleteTrainingRunSerializer,
        responses={
            200: OpenApiResponse(
                response=AutoresearchTrainingRunSerializer,
                description="The completed training run. Call autoresearch-models-list to see the resulting champion/challenger.",
            ),
            400: OpenApiResponse(
                description="Run is already completed or failed, has no recorded iterations, or has no usable model artifact (no bundle and no feature SQL)."
            ),
        },
        summary="Complete a training run",
        description=(
            "Finalize a training run. The backend selects the best iteration (highest holdout score, or the "
            "one you name), decides champion vs challenger via the promotion ladder, and persists the model. "
            "Agents cannot set the champion directly — promotion is server-side."
        ),
    )
    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = request.validated_data
        try:
            training_run = api.complete_run(
                self.team_id,
                self.kwargs["pk"],
                best_iteration_id=data.get("best_iteration_id"),
                model_explanation=data.get("model_explanation") or {},
                recommended_next=data.get("recommended_next") or "",
                distillation=data.get("distillation") or "",
            )
        except TrainingRunNotFound:
            raise NotFound("Training run not found.")
        except AutoresearchConflict as exc:
            raise ValidationError(str(exc)) from exc
        return Response(AutoresearchTrainingRunSerializer(instance=training_run).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="limit",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of prior runs to return (default 5, capped at 20).",
            )
        ],
        responses={
            200: OpenApiResponse(
                response=TrainingRunHistorySerializer,
                description="Prior completed training runs with their iteration trails, for orienting a new run.",
            )
        },
        summary="Read prior training-run history",
        description=(
            "Return recent completed training runs and their iteration trails so a new run can learn "
            "from what was already tried. Scoped to this pipeline first, then same-target sibling "
            "pipelines on the team. Read this before iterating to reuse winning features and avoid "
            "repeating discarded approaches."
        ),
    )
    @action(detail=False, methods=["get"], url_path="history", pagination_class=None)
    def history(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            limit = int(request.query_params.get("limit", 5))
        except (TypeError, ValueError):
            limit = 5
        try:
            history = api.training_run_history(self.team_id, _require_parent_pipeline_id(self), limit=limit)
        except PipelineNotFound as exc:
            raise ValidationError(str(exc)) from exc
        return Response(TrainingRunHistorySerializer(instance=history).data)
