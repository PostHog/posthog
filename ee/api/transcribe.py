"""
ViewSet for audio transcription using OpenAI Whisper API.
"""

from django.conf import settings

import openai
import structlog
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

logger = structlog.get_logger(__name__)


class TranscribeViewSet(TeamAndOrgViewSetMixin, ViewSet):
    scope_object = "conversation"
    permission_classes = [IsAuthenticated]
    authentication_classes = [PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    throttle_classes = [AIBurstRateThrottle, AISustainedRateThrottle]
    parser_classes = [MultiPartParser]

    def create(self, request: Request, *args, **kwargs) -> Response:
        """
        Speech-to-text transcription API.

        Accepts audio files up to 25MB in formats: mp3, mp4, mpeg, mpga, m4a, wav, webm.
        Returns the transcribed text.
        """
        audio_file = request.FILES.get("file")
        if not audio_file:
            return Response(
                {"error": "No audio file provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        api_key = settings.OPENAI_API_KEY
        if not api_key:
            logger.error("openai_api_key_not_configured", team_id=self.team.id)
            return Response(
                {"error": "Transcription service not configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            client = openai.OpenAI(api_key=api_key, base_url=settings.OPENAI_BASE_URL)

            # Pass file as tuple (filename, file_content, content_type) for OpenAI SDK compatibility
            file_tuple = (audio_file.name, audio_file.read(), audio_file.content_type)

            transcript = client.audio.transcriptions.create(
                model="gpt-4o-transcribe",
                file=file_tuple,
                response_format="text",
            )

            logger.info(
                "audio_transcription_completed",
                team_id=self.team.id,
                file_name=audio_file.name,
                file_size=audio_file.size,
            )

            return Response({"text": transcript})

        except openai.BadRequestError as e:
            logger.warning(
                "audio_transcription_bad_request",
                team_id=self.team.id,
                error=str(e),
            )
            return Response(
                {"error": "Invalid audio file or request"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except openai.APIError as e:
            logger.exception(
                "openai_transcription_api_error",
                team_id=self.team.id,
                error=str(e),
            )
            return Response(
                {"error": "Transcription failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as e:
            logger.exception(
                "audio_transcription_unexpected_error",
                team_id=self.team.id,
                error=str(e),
            )
            return Response(
                {"error": "An unexpected error occurred"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
