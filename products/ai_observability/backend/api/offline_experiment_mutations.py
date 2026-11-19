from collections.abc import Mapping
from functools import partial
from typing import TYPE_CHECKING, cast

from drf_spectacular.extensions import OpenApiSerializerExtension
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.auth import is_mcp_request
from posthog.event_usage import report_user_action
from posthog.permissions import PostHogFeatureFlagPermission, is_service_auth

from products.ai_observability.backend.api.analytics import report_on_commit
from products.ai_observability.backend.api.offline_experiment_reads import (
    EXPERIMENT_ID_PARAMETER,
    ITEM_ID_PARAMETER,
    READ_ERROR_RESPONSES,
    RESULT_ID_PARAMETER,
    OfflineExperimentReadViewSet,
)
from products.ai_observability.backend.api.offline_experiment_serializers import (
    ItemPayloadField,
    ResultPayloadField,
    ResultValueField,
    _identifier_field,
)
from products.ai_observability.backend.facade import api as aio
from products.ai_observability.backend.logic.offline_evaluations.mutations import Target
from products.ai_observability.backend.models.offline_evaluations import OfflineEvaluationResult
from products.ai_observability.backend.offline_evaluation_types import JSONValue

if TYPE_CHECKING:
    from drf_spectacular.openapi import AutoSchema
    from drf_spectacular.utils import Direction

MUTATION_ERRORS = {**READ_ERROR_RESPONSES, 409: READ_ERROR_RESPONSES[400]}
MUTATION_ACTIONS = frozenset(
    {
        "update_item",
        "delete_item",
        "update_result",
        "delete_result",
        "update_item_payload",
        "delete_item_payload",
        "update_result_payload",
        "delete_result_payload",
    }
)


class OfflineRevisionSerializer(serializers.Serializer):
    revision = serializers.IntegerField(
        min_value=0, help_text="Revision returned by the latest read of this item, result, or payload."
    )


class OfflineUpdateSerializer(OfflineRevisionSerializer):
    def to_internal_value(self, data: object) -> dict[str, object]:
        if isinstance(data, Mapping):
            unknown = data.keys() - self.fields.keys()
            if unknown:
                raise serializers.ValidationError({str(name): "This field cannot be updated." for name in unknown})
            if not data.keys() - {"revision"}:
                raise serializers.ValidationError("Supply at least one field to update.")
        return super().to_internal_value(data)


class OfflineUpdateSchema(OpenApiSerializerExtension):
    target_class = OfflineUpdateSerializer
    match_subclasses = True

    def map_serializer(self, auto_schema: "AutoSchema", direction: "Direction") -> dict[str, object]:
        schema = auto_schema._map_serializer(self.target, direction, bypass_extensions=True)
        schema["required"] = sorted(name for name, field in self.target.fields.items() if field.required)
        return schema


class OfflineItemUpdateSerializer(OfflineUpdateSerializer):
    case_key = _identifier_field("Case identifier.")
    trial = _identifier_field("Trial identifier.")
    model_version = _identifier_field("Model used for this item.")
    application_trace_id = _identifier_field("Trace for this item's application execution.")


class OfflineResultUpdateSerializer(OfflineUpdateSerializer):
    status = serializers.ChoiceField(
        choices=OfflineEvaluationResult.Status.choices,
        required=False,
        help_text="Execution status for this reported result.",
    )
    value = ResultValueField(
        required=False,
        allow_null=True,
        help_text="Score for a successful result, validated against the pinned version.",
    )
    error_code = _identifier_field("Error code for a failed execution.", max_length=128)


class OfflineItemPayloadUpdateSerializer(OfflineUpdateSerializer):
    payload = ItemPayloadField(help_text="Top-level fields to update. Omitted fields keep their current values.")


class OfflineResultPayloadUpdateSerializer(OfflineUpdateSerializer):
    payload = ResultPayloadField(help_text="Top-level fields to update. Omitted fields keep their current values.")


class OfflineExperimentMutationViewSet(OfflineExperimentReadViewSet):
    permission_classes = [*OfflineExperimentReadViewSet.permission_classes, PostHogFeatureFlagPermission]
    posthog_feature_flag = {
        "ai-observability-offline-evaluation-mutations": sorted(MUTATION_ACTIONS),
    }

    def dangerously_get_required_scopes(self, request: Request, view: viewsets.ViewSetMixin) -> list[str] | None:
        if self.action in MUTATION_ACTIONS:
            scopes = ["evaluation:write"]
            if "result" in self.action or self.action == "delete_item":
                scopes.append("llm_analytics:read")
            return scopes
        return super().dangerously_get_required_scopes(request, view)

    def _mutate_resource(self, request: ValidatedRequest, target: Target) -> Response:
        deleting = request.method == "DELETE"
        if is_service_auth(request) or (deleting and is_mcp_request(request)):
            raise PermissionDenied("Use the direct project API with an evaluation editor credential.")
        data = dict(request.validated_query_data if deleting else request.validated_data)
        revision = data.pop("revision")
        result = aio.mutate_offline_evaluation(
            team_id=self.team_id,
            experiment_id=self._path_id(),
            resource_id=self._path_id("item_id" if target.startswith("item") else "result_id"),
            target=target,
            expected_revision=revision,
            changes=None if deleting else cast(dict[str, JSONValue], data),
            access=self.user_access_control,
        )
        report_on_commit(
            partial(
                report_user_action,
                request.user,
                "llma offline evaluation resource changed",
                {"resource": target, "operation": "delete" if deleting else "update"},
                team=self.team,
                request=request,
            )
        )
        return Response(status=204) if deleting else Response({"revision": result})

    @OfflineExperimentReadViewSet.item.mapping.patch
    @validated_request(
        request_serializer=OfflineItemUpdateSerializer,
        operation_id="ai_observability_offline_experiments_items_partial_update",
        parameters=[EXPERIMENT_ID_PARAMETER, ITEM_ID_PARAMETER],
        responses={200: OfflineRevisionSerializer, **MUTATION_ERRORS},
    )
    def update_item(self, request: ValidatedRequest, **kwargs: object) -> Response:
        return self._mutate_resource(request, "item")

    @OfflineExperimentReadViewSet.item.mapping.delete
    @validated_request(
        query_serializer=OfflineRevisionSerializer,
        operation_id="ai_observability_offline_experiments_items_destroy",
        parameters=[EXPERIMENT_ID_PARAMETER, ITEM_ID_PARAMETER],
        responses={204: None, **MUTATION_ERRORS},
    )
    def delete_item(self, request: ValidatedRequest, **kwargs: object) -> Response:
        return self._mutate_resource(request, "item")

    @validated_request(
        request_serializer=OfflineResultUpdateSerializer,
        operation_id="ai_observability_offline_experiments_results_partial_update",
        parameters=[EXPERIMENT_ID_PARAMETER, RESULT_ID_PARAMETER],
        responses={200: OfflineRevisionSerializer, **MUTATION_ERRORS},
    )
    @action(detail=True, methods=["patch"], url_path=r"results/(?P<result_id>[^/.]+)")
    def update_result(self, request: ValidatedRequest, **kwargs: object) -> Response:
        return self._mutate_resource(request, "result")

    @update_result.mapping.delete
    @validated_request(
        query_serializer=OfflineRevisionSerializer,
        operation_id="ai_observability_offline_experiments_results_destroy",
        parameters=[EXPERIMENT_ID_PARAMETER, RESULT_ID_PARAMETER],
        responses={204: None, **MUTATION_ERRORS},
    )
    def delete_result(self, request: ValidatedRequest, **kwargs: object) -> Response:
        return self._mutate_resource(request, "result")

    @OfflineExperimentReadViewSet.item_payload.mapping.patch
    @validated_request(
        request_serializer=OfflineItemPayloadUpdateSerializer,
        operation_id="ai_observability_offline_experiments_items_payload_partial_update",
        parameters=[EXPERIMENT_ID_PARAMETER, ITEM_ID_PARAMETER],
        responses={200: OfflineRevisionSerializer, **MUTATION_ERRORS},
    )
    def update_item_payload(self, request: ValidatedRequest, **kwargs: object) -> Response:
        return self._mutate_resource(request, "item_payload")

    @OfflineExperimentReadViewSet.item_payload.mapping.delete
    @validated_request(
        query_serializer=OfflineRevisionSerializer,
        operation_id="ai_observability_offline_experiments_items_payload_destroy",
        parameters=[EXPERIMENT_ID_PARAMETER, ITEM_ID_PARAMETER],
        responses={204: None, **MUTATION_ERRORS},
    )
    def delete_item_payload(self, request: ValidatedRequest, **kwargs: object) -> Response:
        return self._mutate_resource(request, "item_payload")

    @OfflineExperimentReadViewSet.result_payload.mapping.patch
    @validated_request(
        request_serializer=OfflineResultPayloadUpdateSerializer,
        operation_id="ai_observability_offline_experiments_results_payload_partial_update",
        parameters=[EXPERIMENT_ID_PARAMETER, RESULT_ID_PARAMETER],
        responses={200: OfflineRevisionSerializer, **MUTATION_ERRORS},
    )
    def update_result_payload(self, request: ValidatedRequest, **kwargs: object) -> Response:
        return self._mutate_resource(request, "result_payload")

    @OfflineExperimentReadViewSet.result_payload.mapping.delete
    @validated_request(
        query_serializer=OfflineRevisionSerializer,
        operation_id="ai_observability_offline_experiments_results_payload_destroy",
        parameters=[EXPERIMENT_ID_PARAMETER, RESULT_ID_PARAMETER],
        responses={204: None, **MUTATION_ERRORS},
    )
    def delete_result_payload(self, request: ValidatedRequest, **kwargs: object) -> Response:
        return self._mutate_resource(request, "result_payload")
