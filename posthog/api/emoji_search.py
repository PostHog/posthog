from typing import Any

from django.utils.cache import patch_vary_headers

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.emoji_search.match import suggest_emojis
from posthog.llm.system_one import SystemOneNotConfigured, SystemOneRequestFailed


class EmojiSearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=64, help_text="Search text that had no direct emoji match.")


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


@extend_schema(extensions={"x-product": "core"})
class EmojiSearchViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = EmojiSearchRequestSerializer
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
        try:
            suggestions = suggest_emojis(request.validated_query_data["query"], team_id=self.team_id)
        except (SystemOneNotConfigured, SystemOneRequestFailed) as error:
            raise EmojiSearchUnavailable() from error
        response = Response(
            EmojiSearchResponseSerializer({"suggestions": suggestions}).data,
            headers={"Cache-Control": "private, max-age=604800"},
        )
        patch_vary_headers(response, ["Cookie", "Authorization"])
        return response
