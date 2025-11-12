import base64

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

import structlog
from posthoganalytics import capture_exception
from rest_framework import serializers, status
from rest_framework.throttling import SimpleRateThrottle

from posthog.api.utils import get_token
from posthog.exceptions import generate_exception_response
from posthog.models import Team
from posthog.models.feedback_audio import FeedbackAudio
from posthog.utils import load_data_from_request
from posthog.utils_cors import cors_response

logger = structlog.get_logger(__name__)

# Audio file size limit: 10MB
MAX_AUDIO_FILE_SIZE = 10 * 1024 * 1024

# 40% buffer for base64 encoding overhead
REPORTED_SIZE_BUFFER_FACTOR = 1.4

# Supported audio MIME types
SUPPORTED_AUDIO_MIME_TYPES = [
    "audio/webm",
    "audio/mp4",
]


class FeedbackAudioUploadThrottle(SimpleRateThrottle):
    """
    Rate limiting for public feedback audio uploads.
    Throttles by API token to prevent abuse while allowing legitimate usage.
    """

    scope = "feedback_audio_upload"
    rate = "100/hour"  # Allow 100 uploads per hour per project

    def __init__(self, token=None):
        super().__init__()
        self.token = token

    def get_cache_key(self, request, view):
        """Throttle by API token instead of user/IP"""
        if self.token:
            return self.cache_format % {"scope": self.scope, "ident": self.token}

        # Fallback to IP if no token
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class FeedbackAudioSerializer(serializers.Serializer):
    feedback_id = serializers.UUIDField()
    audio_mime_type = serializers.CharField(max_length=50)
    audio_size = serializers.IntegerField()
    audio_data = serializers.CharField()  # base64 encoded audio data

    def validate_audio_mime_type(self, value):
        # Extract base MIME type (i.e. remove codec parameters)
        base_mime_type = value.split(";")[0].strip()

        if base_mime_type not in SUPPORTED_AUDIO_MIME_TYPES:
            raise serializers.ValidationError(
                f"Unsupported audio format: {base_mime_type}. Supported formats: {', '.join(SUPPORTED_AUDIO_MIME_TYPES)}"
            )
        # Return normalized MIME type without codec params
        return base_mime_type

    def validate_audio_size(self, value):
        if value <= 0:
            raise serializers.ValidationError("audio_size must be greater than 0")

        if value > MAX_AUDIO_FILE_SIZE:
            raise serializers.ValidationError(
                f"Audio file too large. Maximum size is {MAX_AUDIO_FILE_SIZE / (1024 * 1024):.0f}MB"
            )

        return value

    def validate_audio_data(self, value):
        if not value:
            raise serializers.ValidationError("audio_data is required")

        # Base64 encoding increases size by ~33%, so we add 40% buffer for padding
        max_b64_size = MAX_AUDIO_FILE_SIZE * REPORTED_SIZE_BUFFER_FACTOR
        if len(value) > max_b64_size:
            raise serializers.ValidationError(
                f"Audio data too large. Maximum file size is {MAX_AUDIO_FILE_SIZE / (1024 * 1024):.0f}MB"
            )

        return value

    def create(self, validated_data):
        # Decode audio data for storage
        decoded_audio = base64.b64decode(validated_data["audio_data"], validate=True)

        feedback_audio = FeedbackAudio.objects.create(
            team_id=self.context["team_id"],
            feedback_id=validated_data["feedback_id"],
            audio_size=validated_data["audio_size"],
            content_type=validated_data["audio_mime_type"],
        )

        # Save the audio file to object storage
        feedback_audio.save_audio_data(decoded_audio)

        return feedback_audio


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def feedback_audio_upload(request):
    """
    Public endpoint for audio feedback uploads at /ingest/api/feedback/audio/
    Accepts JSON data with base64-encoded audio and metadata.
    """
    if request.method == "OPTIONS":
        return cors_response(request, HttpResponse(""))

    data = load_data_from_request(request)
    token = get_token(data, request)

    # Apply rate limiting using the extracted token
    throttle = FeedbackAudioUploadThrottle(token=token)
    if not throttle.allow_request(request, None):
        return cors_response(
            request,
            generate_exception_response(
                "feedback_audio",
                "Upload rate limit exceeded. Please try again later.",
                type="rate_limit_error",
                code="rate_limit_exceeded",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            ),
        )

    if not token:
        return cors_response(
            request,
            generate_exception_response(
                "feedback_audio",
                "Authentication failed",
                type="authentication_error",
                code="authentication_failed",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    try:
        team = Team.objects.get_team_from_cache_or_token(token)
        if team is None:
            return cors_response(
                request,
                generate_exception_response(
                    "feedback_audio",
                    "Authentication failed",
                    type="authentication_error",
                    code="authentication_failed",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                ),
            )

        # Only POST requests reach here due to @require_http_methods decorator
        serializer = FeedbackAudioSerializer(data=data, context={"team_id": team.id})

        if serializer.is_valid():
            feedback_audio = serializer.save()

            response_data = {
                "success": True,
                "id": feedback_audio.id,
                "feedback_id": feedback_audio.feedback_id,
                "message": "Audio feedback uploaded successfully",
            }
            return cors_response(request, JsonResponse(response_data, status=status.HTTP_201_CREATED))
        else:
            return cors_response(
                request,
                JsonResponse(
                    {"success": False, "errors": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                ),
            )

    except Exception as e:
        logger.error("feedback_audio_endpoint_error", error=str(e), exc_info=True)
        capture_exception(e)
        return cors_response(
            request,
            JsonResponse(
                {"success": False, "error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
        )


@require_http_methods(["GET", "OPTIONS"])
def feedback_audio_download(request, feedback_audio_id):
    """
    Download feedback audio file by ID using API token for authentication.
    URL: /api/feedback_audio/{id}/download?token=<api_key>
    Requires both authenticated user and valid API token with team access.
    """
    if request.method == "OPTIONS":
        return cors_response(request, HttpResponse(""))

    try:
        # Ensure user is authenticated
        if not request.user.is_authenticated:
            return cors_response(
                request,
                JsonResponse(
                    {"error": "Authentication failed"},
                    status=status.HTTP_401_UNAUTHORIZED,
                ),
            )

        # Get token from request
        token = get_token(None, request)
        if not token:
            return cors_response(
                request,
                JsonResponse(
                    {"error": "Authentication failed"},
                    status=status.HTTP_400_BAD_REQUEST,
                ),
            )

        # Resolve team from token
        team = Team.objects.get_team_from_cache_or_token(token)
        if not team:
            return cors_response(
                request,
                JsonResponse(
                    {"error": "Authentication failed"},
                    status=status.HTTP_401_UNAUTHORIZED,
                ),
            )

        # Check if user has access to this team
        if not request.user.teams.filter(id=team.id).exists():
            return cors_response(
                request,
                JsonResponse(
                    {"error": "Authentication failed"},
                    status=status.HTTP_403_FORBIDDEN,
                ),
            )

        # Get feedback audio record for this team
        try:
            feedback_audio = FeedbackAudio.objects.get(feedback_id=feedback_audio_id, team_id=team.id)
        except FeedbackAudio.DoesNotExist:
            return cors_response(
                request,
                JsonResponse(
                    {"error": "Feedback audio not found."},
                    status=status.HTTP_404_NOT_FOUND,
                ),
            )

        audio_data = feedback_audio.get_audio_data()
        if not audio_data:
            return cors_response(
                request,
                JsonResponse(
                    {"error": "Audio file not found."},
                    status=status.HTTP_404_NOT_FOUND,
                ),
            )

        # Create HTTP response with audio data
        response = HttpResponse(audio_data, content_type=feedback_audio.content_type)

        # Set headers for proper audio playback
        response["Content-Length"] = str(len(audio_data))
        response["Accept-Ranges"] = "bytes"
        response["Cache-Control"] = "public, max-age=3600"

        return cors_response(request, response)

    except Exception as e:
        logger.error(
            "feedback_audio_download_error",
            audio_id=feedback_audio_id,
            error=str(e),
            exc_info=True,
        )
        capture_exception(e)
        return cors_response(
            request,
            JsonResponse(
                {"error": "Failed to download audio file"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
        )
