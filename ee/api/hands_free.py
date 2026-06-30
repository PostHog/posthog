"""Backend support for Max's hands-free mode.

Hands-free mode lets a user talk to Max with their hands and eyes off the screen — built
for mobile-web (gym, walking, driving). Speech-to-text runs via ElevenLabs Scribe directly
from the browser using single-use tokens minted here so the ElevenLabs API key never
reaches the client. Text-to-speech is proxied through the synthesize endpoint, again to
keep the API key server-side; mp3 bytes stream back to the browser.
"""

from typing import Any

from django.conf import settings
from django.http import StreamingHttpResponse

import requests
import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from prometheus_client import Counter
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.streaming import streaming_response
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.rate_limit import (
    MaxHandsFreeSynthesizeBurstRateThrottle,
    MaxHandsFreeSynthesizeSustainedRateThrottle,
    MaxHandsFreeTokenBurstRateThrottle,
    MaxHandsFreeTokenSustainedRateThrottle,
)

from products.posthog_ai.backend.models.assistant import Conversation

logger = structlog.get_logger(__name__)

ELEVENLABS_TIMEOUT_SECONDS = (5, 10)
# Generous enough for any Max summary, tight enough that an attacker minting at the
# throttle ceiling can't ramp Scribe cost into the stratosphere.
TTS_MAX_INPUT_CHARS = 2000

# One counter, partitioned by outcome — lets us track abuse signal (provider rejection
# spikes, repeated empty tokens) and steady-state cost (ok counts ≈ Scribe spend) without
# blowing up cardinality via per-team labels.
HANDS_FREE_TOKEN_COUNTER = Counter(
    "max_hands_free_token_total",
    "Outcomes for ElevenLabs Scribe single-use token mints from the hands-free endpoint.",
    labelnames=["outcome"],
)
HANDS_FREE_SYNTHESIZE_COUNTER = Counter(
    "max_hands_free_synthesize_total",
    "Outcomes for ElevenLabs TTS proxy requests from the hands-free endpoint.",
    labelnames=["outcome"],
)
HANDS_FREE_SYNTHESIZE_CHARS_COUNTER = Counter(
    "max_hands_free_synthesize_chars_total",
    "Total characters submitted for ElevenLabs TTS — proxy for TTS spend.",
)


class HandsFreeNotConfigured(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Hands-free mode is not configured on this PostHog instance."
    default_code = "hands_free_not_configured"


class HandsFreeProviderError(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The hands-free provider rejected the request."
    default_code = "hands_free_provider_error"


class SynthesizeSerializer(serializers.Serializer):
    text = serializers.CharField(
        required=True,
        max_length=TTS_MAX_INPUT_CHARS,
        help_text="The text the assistant should speak aloud.",
    )


def _require_api_key(counter: Counter) -> str:
    api_key = settings.ELEVENLABS_API_KEY
    if not api_key:
        counter.labels(outcome="missing_key").inc()
        logger.warning("max_hands_free_api_key_missing")
        raise HandsFreeNotConfigured()
    return api_key


class MaxHandsFreeViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "INTERNAL"
    # Hands-free actions are list-level and don't operate on any model — DRF's GenericViewSet
    # needs a queryset attribute for the routing scaffolding but it is never read.
    queryset = Conversation.objects.none()
    # drf-spectacular requires every viewset to declare a serializer_class for OpenAPI
    # generation. The `token` action takes no body and `synthesize` overrides this via
    # its @extend_schema decorator, so SynthesizeSerializer is purely the schema-default
    # — never instantiated by the viewset's own get_serializer().
    serializer_class = SynthesizeSerializer
    # Server-side gate on the same feature flag the frontend checks — without it an
    # authenticated project member could POST directly to /token/ or /synthesize/ and
    # rack up ElevenLabs spend even when their org doesn't have hands-free enabled.
    posthog_feature_flag = "max-hands-free"
    permission_classes = [IsAuthenticated, PostHogFeatureFlagPermission]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(
        detail=False,
        methods=["POST"],
        url_path="token",
        throttle_classes=[MaxHandsFreeTokenBurstRateThrottle, MaxHandsFreeTokenSustainedRateThrottle],
    )
    def token(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Mint a single-use ElevenLabs Scribe realtime token.

        The browser uses the token to open a WebSocket directly to ElevenLabs — audio never
        transits PostHog infrastructure. Tokens are time-bound (15 min) and single-use; the
        per-team rate limit on this endpoint caps how often a user can mint new ones.

        Never logs the upstream response body — provider error responses can echo PII back and
        we don't want any of that landing in structured logs.
        """
        api_key = _require_api_key(HANDS_FREE_TOKEN_COUNTER)
        try:
            upstream = requests.post(
                f"{settings.ELEVENLABS_API_BASE_URL}/v1/single-use-token/realtime_scribe",
                headers={"xi-api-key": api_key},
                timeout=ELEVENLABS_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            HANDS_FREE_TOKEN_COUNTER.labels(outcome="provider_unreachable").inc()
            logger.exception("max_hands_free_token_failed")
            raise HandsFreeProviderError("Failed to reach the hands-free provider.")

        if upstream.status_code != status.HTTP_200_OK:
            HANDS_FREE_TOKEN_COUNTER.labels(outcome="provider_rejected").inc()
            logger.warning("max_hands_free_token_rejected", status_code=upstream.status_code)
            raise HandsFreeProviderError(f"Hands-free provider returned {upstream.status_code}.")

        try:
            body = upstream.json()
            if not isinstance(body, dict):
                raise ValueError("Expected JSON object")
            token: str = body.get("token", "")
        except ValueError:
            HANDS_FREE_TOKEN_COUNTER.labels(outcome="provider_rejected").inc()
            logger.warning("max_hands_free_token_malformed_json", status_code=upstream.status_code)
            raise HandsFreeProviderError("Hands-free provider returned a malformed response.")
        if not token:
            HANDS_FREE_TOKEN_COUNTER.labels(outcome="empty_token").inc()
            logger.warning("max_hands_free_token_empty")
            raise HandsFreeProviderError("Hands-free provider returned an empty token.")
        HANDS_FREE_TOKEN_COUNTER.labels(outcome="ok").inc()
        return Response({"token": token})

    @extend_schema(request=SynthesizeSerializer, responses={200: OpenApiTypes.BINARY})
    @action(
        detail=False,
        methods=["POST"],
        url_path="synthesize",
        parser_classes=[JSONParser],
        throttle_classes=[MaxHandsFreeSynthesizeBurstRateThrottle, MaxHandsFreeSynthesizeSustainedRateThrottle],
    )
    def synthesize(self, request: Request, *args: Any, **kwargs: Any) -> StreamingHttpResponse:
        """Proxy text-to-speech to ElevenLabs, streaming mp3 audio back to the browser.

        The viewset has no per-action `parser_classes` other than this one because the
        token endpoint takes no body. Putting JSONParser here keeps the rest of the
        viewset parser-free.
        """
        serializer = SynthesizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        text = serializer.validated_data["text"]

        api_key = _require_api_key(HANDS_FREE_SYNTHESIZE_COUNTER)
        voice_id = settings.ELEVENLABS_VOICE_ID
        if not voice_id:
            HANDS_FREE_SYNTHESIZE_COUNTER.labels(outcome="missing_voice_id").inc()
            logger.warning("max_hands_free_voice_id_missing")
            raise HandsFreeNotConfigured("Voice ID is not configured.")
        try:
            upstream = requests.post(
                f"{settings.ELEVENLABS_API_BASE_URL}/v1/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": api_key,
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                },
                json={"text": text, "model_id": settings.ELEVENLABS_TTS_MODEL_ID},
                timeout=ELEVENLABS_TIMEOUT_SECONDS,
                stream=True,
            )
        except requests.RequestException:
            HANDS_FREE_SYNTHESIZE_COUNTER.labels(outcome="provider_unreachable").inc()
            logger.exception("max_hands_free_synthesize_failed")
            raise HandsFreeProviderError("Failed to reach the hands-free provider.")

        if upstream.status_code != status.HTTP_200_OK:
            HANDS_FREE_SYNTHESIZE_COUNTER.labels(outcome="provider_rejected").inc()
            # ElevenLabs 4xx responses are JSON describing the account/quota state — not the
            # user's input. Safe to log a snippet so devs can see "quota_exceeded" vs
            # "voice_not_found" without hitting the dashboard.
            body_preview = ""
            try:
                body_preview = upstream.text[:300].replace("\n", " ")
            except Exception:
                pass
            logger.warning(
                "max_hands_free_synthesize_rejected",
                status_code=upstream.status_code,
                body_preview=body_preview,
            )
            upstream.close()
            raise HandsFreeProviderError(f"Hands-free provider returned {upstream.status_code}.")

        # Anything between the upstream 200 and returning the StreamingHttpResponse can
        # raise (a counter labels() call, the StreamingHttpResponse constructor, the
        # header assignment). Without an explicit close on those paths the connection
        # only releases when the unconsumed generator is garbage collected — which is
        # not guaranteed to be prompt under load. Guard the whole block.
        try:
            HANDS_FREE_SYNTHESIZE_COUNTER.labels(outcome="ok").inc()
            HANDS_FREE_SYNTHESIZE_CHARS_COUNTER.inc(len(text))

            def stream_and_close() -> Any:
                try:
                    yield from upstream.iter_content(chunk_size=4096)
                finally:
                    upstream.close()

            response = streaming_response(
                stream_and_close(), content_type="audio/mpeg", headers={"Cache-Control": "no-store"}
            )
        except Exception:
            upstream.close()
            raise
        return response
