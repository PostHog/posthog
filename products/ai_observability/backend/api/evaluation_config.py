from datetime import datetime

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field, extend_schema_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.permissions import AccessControlPermission

from ..constants import trial_eval_deprecation_date
from ..models.evaluation_config import EvaluationConfig
from ..models.provider_keys import LLMProviderKey
from .metrics import llma_track_latency
from .provider_keys import LLMProviderKeySerializer


@extend_schema_serializer(many=False)
class EvaluationConfigSerializer(serializers.ModelSerializer):
    trial_evals_remaining = serializers.IntegerField(
        read_only=True,
        help_text="Trial runs remaining — a getting-started affordance only; evals should use the team's own provider key.",
    )
    trial_grandfathered = serializers.BooleanField(
        source="is_trial_grandfathered",
        read_only=True,
        help_text="True while this team keeps PostHog-funded trial inference during the deprecation window (i.e. it is mid-trial and the cutoff has not passed). False means the team must use its own provider key.",
    )
    trial_deprecation_date = serializers.SerializerMethodField(
        help_text="Timestamp after which trial evaluations are fully removed and every team must use its own provider key.",
    )
    active_provider_key = LLMProviderKeySerializer(
        read_only=True,
        allow_null=True,
        help_text="Provider key used to run llm_judge evals; null if none configured yet.",
    )

    @extend_schema_field(OpenApiTypes.DATETIME)
    def get_trial_deprecation_date(self, _obj: EvaluationConfig) -> datetime:
        return trial_eval_deprecation_date()

    class Meta:
        model = EvaluationConfig
        fields = [
            "trial_eval_limit",
            "trial_evals_used",
            "trial_evals_remaining",
            "trial_grandfathered",
            "trial_deprecation_date",
            "active_provider_key",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "trial_eval_limit",
            "trial_evals_used",
            "trial_evals_remaining",
            "trial_grandfathered",
            "active_provider_key",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "trial_eval_limit": {
                "help_text": "Cap on trial runs — a getting-started affordance only, not for ongoing evals (use the team's own key).",
            },
            "trial_evals_used": {
                "help_text": "Trial runs consumed (getting-started affordance only).",
            },
            "created_at": {"help_text": "Timestamp when the evaluation config row was created."},
            "updated_at": {"help_text": "Timestamp when the evaluation config row was last modified."},
        }


class EvaluationConfigSetActiveKeyRequestSerializer(serializers.Serializer):
    key_id = serializers.UUIDField(
        help_text=(
            "UUID of an existing LLM provider key (state must be 'ok') to mark as the active key for "
            "running llm_judge evaluations team-wide."
        ),
    )


class EvaluationConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Team-level evaluation configuration"""

    scope_object = "evaluation"
    # `set_active_key` is a custom @action and `list` lives on a plain ViewSet, so neither maps to
    # ScopeBasePermission's default action lists. Spell them out explicitly — without this, every
    # personal-API-key request 403s with "This action does not support Personal API Key access".
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["set_active_key"]
    serializer_class = _FallbackSerializer
    permission_classes = [IsAuthenticated, AccessControlPermission]

    @extend_schema(
        operation_id="llm_analytics_evaluation_config_retrieve",
        responses={200: EvaluationConfigSerializer},
    )
    @llma_track_latency("llma_evaluation_config_list")
    @monitor(feature=None, endpoint="llma_evaluation_config_list", method="GET")
    def list(self, request: Request, **kwargs) -> Response:
        """Get the evaluation config for this team"""
        config, _ = EvaluationConfig.objects.get_or_create(team_id=self.team_id)
        serializer = EvaluationConfigSerializer(config)
        return Response(serializer.data)

    @validated_request(
        request_serializer=EvaluationConfigSetActiveKeyRequestSerializer,
        responses={200: OpenApiResponse(response=EvaluationConfigSerializer)},
    )
    @action(detail=False, methods=["post"])
    @llma_track_latency("llma_evaluation_config_set_active_key")
    @monitor(feature=None, endpoint="llma_evaluation_config_set_active_key", method="POST")
    def set_active_key(self, request: ValidatedRequest, **kwargs) -> Response:
        """Set the active provider key for evaluations"""
        key_id = request.validated_data["key_id"]

        try:
            key = LLMProviderKey.objects.get(id=key_id, team_id=self.team_id)
        except LLMProviderKey.DoesNotExist:
            return Response(
                {"detail": "Key not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if key.state != LLMProviderKey.State.OK:
            return Response(
                {"detail": f"Cannot activate key with state '{key.state}'. Please validate the key first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        config, _ = EvaluationConfig.objects.get_or_create(team_id=self.team_id)
        old_key = config.active_provider_key
        config.active_provider_key = key
        config.save(update_fields=["active_provider_key", "updated_at"])

        report_user_action(
            request.user,
            "llma evaluation config active key set",
            {
                "key_id": str(key.id),
                "old_key_id": str(old_key.id) if old_key else None,
            },
            team=self.team,
            request=self.request,
        )

        serializer = EvaluationConfigSerializer(config)
        return Response(serializer.data)
