from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import AccessControlPermission

from ..models.model_configuration import LLMModelConfiguration, provider_requires_key
from ..models.provider_keys import LLMProvider, LLMProviderKey
from .metrics import llma_track_latency

SUPPORTED_PROVIDERS: list[str] = [choice[0] for choice in LLMProvider.choices]


class LLMModelInfoSerializer(serializers.Serializer):
    id = serializers.CharField(
        help_text="Provider-specific model identifier (e.g. 'gpt-4o-mini', 'claude-3-5-sonnet-20241022')."
    )
    provider = serializers.CharField(
        help_text=(
            "Provider this model belongs to. Pass this value together with `id` when configuring an llm_judge "
            "evaluation."
        )
    )


class LLMProviderModelsSummarySerializer(serializers.Serializer):
    provider = serializers.CharField(help_text="Supported provider value, exactly as the `provider` param accepts it.")
    model_count = serializers.IntegerField(help_text="How many of this provider's models appear in `models`.")
    requires_provider_key = serializers.BooleanField(
        help_text=(
            "True when this provider's models can only be listed by passing `key_id` for one of the team's provider "
            "keys. PostHog funds no models for it, so `model_count` is 0 until a key is supplied."
        )
    )


@extend_schema_serializer(many=False)
class LLMModelsListResponseSerializer(serializers.Serializer):
    models = LLMModelInfoSerializer(
        many=True,
        help_text=(
            "Models supported for the requested provider, or for every supported provider when `provider` is omitted."
        ),
    )
    providers = LLMProviderModelsSummarySerializer(
        many=True,
        help_text=(
            "One entry per provider covered by this response. Read it to tell an unsupported provider apart from a "
            "provider whose models need a team key before they can be listed."
        ),
    )


class LLMModelsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """List available models, for one provider or for every supported provider."""

    # Shared by the evaluations, taggers, and playground model pickers, so it sits on the
    # product-wide llm_analytics resource rather than any one of their resources.
    scope_object = "llm_analytics"
    serializer_class = _FallbackSerializer
    permission_classes = [IsAuthenticated, AccessControlPermission]

    @extend_schema(
        operation_id="llm_analytics_models_retrieve",
        parameters=[
            OpenApiParameter(
                name="provider",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=SUPPORTED_PROVIDERS,
                description=(
                    "LLM provider to list models for. Omit it to list every supported provider and its models in one "
                    "call."
                ),
            ),
            OpenApiParameter(
                name="key_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Optional provider key UUID. When supplied, models reachable with that specific key are "
                    "returned (useful for Azure OpenAI, where the deployment list depends on the configured "
                    "endpoint). A key belongs to exactly one provider, so `provider` may be omitted alongside it; "
                    "when both are given they must agree."
                ),
            ),
        ],
        responses={200: LLMModelsListResponseSerializer},
    )
    @llma_track_latency("llma_models_list")
    @monitor(feature=None, endpoint="llma_models_list", method="GET")
    def list(self, request: Request, **_kwargs) -> Response:
        provider = request.query_params.get("provider") or None
        key_id = request.query_params.get("key_id") or None

        if provider is not None and provider not in SUPPORTED_PROVIDERS:
            return Response(
                {
                    "detail": (
                        f"Invalid provider '{provider}'. Must be one of: {', '.join(SUPPORTED_PROVIDERS)}. "
                        "Omit the provider param to list every supported provider."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        provider_key = None
        if key_id:
            try:
                provider_key = LLMProviderKey.objects.get(id=key_id, team_id=self.team_id)
            except (LLMProviderKey.DoesNotExist, DjangoValidationError):
                # DjangoValidationError covers a key_id that isn't a well-formed UUID, which the ORM
                # rejects while building the query rather than returning an empty result.
                return Response(
                    {"detail": f"No provider key '{key_id}' in this project. List the team's provider keys first."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            if provider is not None and provider_key.provider != provider:
                return Response(
                    {
                        "detail": (
                            f"Key '{key_id}' belongs to provider '{provider_key.provider}', not '{provider}'. "
                            "Omit the provider param to use the key's own provider."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            provider = provider_key.provider

        requested_providers = [provider] if provider is not None else SUPPORTED_PROVIDERS

        models: list[dict[str, str]] = []
        providers: list[dict[str, Any]] = []
        for candidate in requested_providers:
            config = LLMModelConfiguration(
                provider=candidate,
                provider_key=provider_key,
                team_id=self.team_id,
            )
            available = config.get_available_models()
            models.extend({"id": model, "provider": candidate} for model in available)
            providers.append(
                {
                    "provider": candidate,
                    "model_count": len(available),
                    "requires_provider_key": provider_requires_key(candidate),
                }
            )

        # Serializing rather than returning the dicts directly keeps the wire shape tied to the
        # response schema the generated frontend and MCP types are built from.
        return Response(LLMModelsListResponseSerializer({"models": models, "providers": providers}).data)
