from typing import Any, cast

from django.utils.cache import patch_vary_headers

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import SessionAuthentication
from posthog.emoji_search.match import suggest_emojis
from posthog.llm.system_one import SystemOneNotConfigured, SystemOneRequestFailed

logger = structlog.get_logger(__name__)


class EmojiSearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(min_length=3, max_length=64, help_text="Search text that had no direct emoji match.")


class EmojiSuggestionSerializer(serializers.Serializer):
    emoji = serializers.CharField(help_text="The suggested emoji character.")
    label = serializers.CharField(help_text="The emoji's English name.")  # type: ignore[assignment]


class EmojiSearchResponseSerializer(serializers.Serializer):
    suggestions = EmojiSuggestionSerializer(many=True, help_text="Related emojis, or an empty list.")


class EmojiSearchUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Emoji suggestions are unavailable right now."
    default_code = "emoji_search_unavailable"


class EmojiSearchThrottle(UserRateThrottle):
    scope = "emoji_search"
    rate = "60/minute"


class EmojiSearchDailyThrottle(UserRateThrottle):
    scope = "emoji_search_daily"
    rate = "3000/day"

    def get_cache_key(self, request: Request, view: APIView) -> str:
        return self.cache_format % {"scope": self.scope, "ident": cast("EmojiSearchViewSet", view).team_id}


class EmojiSearchSessionPermission(BasePermission):
    message = "Emoji suggestions are available only in the web app."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return isinstance(request.successful_authenticator, SessionAuthentication)


@extend_schema(extensions={"x-product": "core"})
class EmojiSearchViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = EmojiSearchRequestSerializer
    permission_classes = [EmojiSearchSessionPermission]
    throttle_classes = [EmojiSearchThrottle]

    @validated_request(
        query_serializer=EmojiSearchRequestSerializer,
        responses={
            200: OpenApiResponse(response=EmojiSearchResponseSerializer, description="Suggested emojis."),
            503: OpenApiResponse(description="The decision model is unavailable."),
        },
        summary="Suggest emojis for an unmatched search",
    )
    @action(detail=False, methods=["GET"])
    def suggest(self, request: Request, **kwargs: Any) -> Response:
        def check_daily_throttle() -> None:
            throttle = EmojiSearchDailyThrottle()
            if not throttle.allow_request(request, self):
                self.throttled(request, wait=throttle.wait() or 0)

        try:
            result = suggest_emojis(
                request.validated_query_data["query"], team_id=self.team_id, before_model_call=check_daily_throttle
            )
        except (SystemOneNotConfigured, SystemOneRequestFailed) as error:
            logger.warning("emoji_search_unavailable", team_id=self.team_id, reason=type(error).__name__)
            raise EmojiSearchUnavailable() from error
        response = Response(
            EmojiSearchResponseSerializer({"suggestions": result.suggestions}).data,
            headers={"Cache-Control": "private, max-age=604800" if result.cacheable else "no-store"},
        )
        patch_vary_headers(response, ["Cookie", "Authorization"])
        return response
