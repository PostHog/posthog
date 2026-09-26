"""
The filter picker's search intent endpoint: which tab does a search belong to?

Validate JSON via serializers, call the classifier, return serialized responses. No business logic here.
"""

from typing import Any, cast

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.llm.system_one import SystemOneNotConfigured, SystemOneRequestFailed
from posthog.models import User
from posthog.taxonomic_search_intent.classify import classify_search_intent, search_intent_enabled
from posthog.taxonomic_search_intent.contracts import SearchIntentRequest, SearchIntentSource

logger = structlog.get_logger(__name__)

MAX_SEARCH_QUERY_CHARS = 200
MAX_GROUP_TYPE_CHARS = 100
MAX_GROUP_TYPES = 64


class SearchIntentRequestSerializer(serializers.Serializer):
    query = serializers.CharField(
        max_length=MAX_SEARCH_QUERY_CHARS,
        allow_blank=True,
        trim_whitespace=True,
        help_text="What the person typed into the filter picker search box.",
    )
    active_group_type = serializers.CharField(
        max_length=MAX_GROUP_TYPE_CHARS,
        help_text="The picker tab that is open, as a taxonomic group type such as event_properties.",
    )
    available_group_types = serializers.ListField(
        child=serializers.CharField(max_length=MAX_GROUP_TYPE_CHARS),
        max_length=MAX_GROUP_TYPES,
        help_text="The taxonomic group types the picker shows. The answer is always one of these, or null.",
    )
    scene = serializers.RegexField(
        r"^[A-Za-z0-9_-]{1,64}$",
        required=False,
        allow_null=True,
        help_text="The id of the scene the picker is open in, such as Insight or Replay.",
    )


class SearchIntentResponseSerializer(serializers.Serializer):
    group_type = serializers.CharField(
        allow_null=True,
        help_text="The taxonomic group type the search most likely belongs to, or null if it was not classified.",
    )
    confidence = serializers.FloatField(
        help_text="How far the chosen group stands out from the rest, from 0 (a coin flip) to 1.",
    )
    is_confident = serializers.BooleanField(
        help_text="Whether the confidence is high enough to act on, for example to suggest a different tab.",
    )
    suggests_switch = serializers.BooleanField(
        help_text="Whether the picker should suggest switching from the open tab to group_type.",
    )
    method = serializers.ChoiceField(
        choices=SearchIntentSource.choices,
        help_text="How the answer was found: a value pattern, the decision model, or not at all.",
    )
    prompt_version = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "The version of the managed search intent prompt the model read. Null for a value pattern, "
            "a skipped search, or the bundled fallback prompt."
        ),
    )


class SearchIntentUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The decision model is not available right now. Try again in a moment."
    default_code = "search_intent_unavailable"


# One search box sends one request per pause in typing, so these rates are far above the AI throttles and
# are separate from them: a person who filters a lot must not lose their PostHog AI budget.
class SearchIntentBurstThrottle(UserRateThrottle):
    scope = "taxonomic_search_intent_burst"
    rate = "120/minute"


class SearchIntentSustainedThrottle(UserRateThrottle):
    scope = "taxonomic_search_intent_sustained"
    rate = "3000/day"


@extend_schema(extensions={"x-product": "core"})
class SearchIntentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = SearchIntentRequestSerializer
    throttle_classes = [SearchIntentBurstThrottle, SearchIntentSustainedThrottle]

    @validated_request(
        request_serializer=SearchIntentRequestSerializer,
        responses={
            200: OpenApiResponse(response=SearchIntentResponseSerializer, description="The most likely tab."),
            404: OpenApiResponse(description="Search intent is not enabled for this person."),
            503: OpenApiResponse(description="The decision model did not answer in time."),
        },
        summary="Classify a filter picker search",
        description="Guess which filter picker tab a search belongs to, so the picker can suggest or promote it.",
    )
    @action(detail=False, methods=["POST"])
    def classify(self, request: Request, **kwargs: Any) -> Response:
        data = request.validated_data
        search = SearchIntentRequest(
            team_id=self.team_id,
            query=data["query"],
            active_group_type=data["active_group_type"],
            available_group_types=tuple(data["available_group_types"]),
            scene=data.get("scene"),
        )
        user = cast(User, request.user)
        if not search_intent_enabled(str(user.distinct_id), str(self.organization_id)):
            raise NotFound()
        try:
            intent = classify_search_intent(search)
        except (SystemOneNotConfigured, SystemOneRequestFailed) as error:
            # The picker works without an answer, so every model failure is the same "not now" to the caller.
            logger.warning("taxonomic_search_intent_unavailable", team_id=self.team_id, reason=type(error).__name__)
            raise SearchIntentUnavailable() from error
        return Response(
            SearchIntentResponseSerializer(
                {
                    "group_type": intent.group_type,
                    "confidence": intent.confidence,
                    "is_confident": intent.is_confident,
                    "suggests_switch": intent.suggests_switch,
                    "method": intent.source,
                    "prompt_version": intent.prompt_version,
                }
            ).data
        )
