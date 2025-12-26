from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from posthog.api.llm_gateway.http import LLMGatewayViewSet
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle


class TranscribeViewSet(TeamAndOrgViewSetMixin, ViewSet):
    """
    Speech-to-text transcription API.
    """

    scope_object = "conversation"
    permission_classes = [IsAuthenticated]
    authentication_classes = [PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    throttle_classes = [AIBurstRateThrottle, AISustainedRateThrottle]
    parser_classes = [MultiPartParser]

    def create(self, request: Request, *args, **kwargs) -> Response:
        gateway = LLMGatewayViewSet()
        gateway.team = self.team
        gateway.organization = self.organization
        gateway.request = request
        gateway.kwargs = self.kwargs
        gateway.args = self.args
        gateway.format_kwarg = self.format_kwarg

        return gateway.audio_transcriptions(request, *args, **kwargs)
