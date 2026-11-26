"""DRF views for agent_transcripts. They validate input, call the facade and serialize its contracts."""

from typing import cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle, SimpleRateThrottle
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.rate_limit import PersonalApiKeyRateThrottle

from ..facade import api
from ..facade.contracts import (
    ALLOWED_TRANSCRIPT_EXTENSIONS,
    MAX_TRANSCRIPT_SIZE_BYTES,
    MEGABYTE,
    CompleteUploadInput,
    InvalidSubmissionState,
    StartUploadInput,
    SubmissionNotFound,
    TranscriptStorageUnavailable,
    UploadRejected,
)
from ..facade.enums import SecretKind, SubmissionAction, SubmissionStatus, TranscriptAgent, UploadRejectionReason
from .serializers import (
    AgentTranscriptErrorSerializer,
    CustomerSubmissionStateSerializer,
    PresignedUploadSerializer,
    StartUploadRequestSerializer,
)

SECRET_DESCRIPTIONS: dict[SecretKind, str] = {
    SecretKind.POSTHOG_PERSONAL_API_KEY: "a PostHog personal API key",
    SecretKind.POSTHOG_SECRET_KEY: "a PostHog secret key",
    SecretKind.POSTHOG_OAUTH_TOKEN: "a PostHog OAuth token",
    SecretKind.PROVIDER_API_KEY: "an AI provider API key",
    SecretKind.AWS_ACCESS_KEY_ID: "an AWS access key ID",
    SecretKind.GITHUB_TOKEN: "a GitHub token",
    SecretKind.GITLAB_TOKEN: "a GitLab token",
    SecretKind.GOOGLE_API_KEY: "a Google API key",
    SecretKind.SLACK_TOKEN: "a Slack token",
    SecretKind.PRIVATE_KEY: "a private key",
}

REJECTION_MESSAGES: dict[UploadRejectionReason, str] = {
    UploadRejectionReason.NOT_UPLOADED: "No file was uploaded. Upload the transcript file, then try again.",
    UploadRejectionReason.EMPTY: "The transcript file is empty. Choose the file that contains the conversation.",
    UploadRejectionReason.TOO_LARGE: (
        f"The transcript file is larger than {MAX_TRANSCRIPT_SIZE_BYTES // MEGABYTE} MB. Choose a smaller file."
    ),
    UploadRejectionReason.UNSUPPORTED_EXTENSION: (
        f"Upload the transcript as a {', '.join(ALLOWED_TRANSCRIPT_EXTENSIONS)} file."
    ),
    UploadRejectionReason.NOT_TEXT: (
        "The file isn't a text file. Export the conversation as text, JSON or Markdown, then upload that file."
    ),
}

START_UPLOAD_REFUSED_MESSAGES: dict[SubmissionStatus, str] = {
    SubmissionStatus.SUBMITTED: (
        "Your transcript is in review. You can upload a new one only if the reviewer asks for changes."
    ),
    SubmissionStatus.APPROVED: "Your organization's transcript was already reviewed, so you can't upload another one.",
    SubmissionStatus.DECLINED: "Your organization's transcript was already reviewed, so you can't upload another one.",
}

NO_PENDING_UPLOAD_MESSAGE = "There's no upload to finish. Start a new upload, then try again."
STORAGE_UNAVAILABLE_MESSAGE = "Couldn't reach file storage. Try again in a few minutes."


class SubmissionConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = NO_PENDING_UPLOAD_MESSAGE
    default_code = "invalid_state"


class StorageUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = STORAGE_UNAVAILABLE_MESSAGE
    default_code = "storage_unavailable"


def _rejection_error(rejection: UploadRejected) -> ValidationError:
    if rejection.reason == UploadRejectionReason.CONTAINS_SECRET and rejection.secret_kind is not None:
        detail = (
            f"The transcript contains what looks like {SECRET_DESCRIPTIONS[rejection.secret_kind]}. "
            "Remove it from the file, then upload the file again."
        )
    else:
        detail = REJECTION_MESSAGES[rejection.reason]

    return ValidationError(detail=detail, code=rejection.reason.value)


def _conflict_error(error: InvalidSubmissionState) -> SubmissionConflict:
    if error.action == SubmissionAction.START_UPLOAD:
        return SubmissionConflict(detail=START_UPLOAD_REFUSED_MESSAGES[error.status])

    return SubmissionConflict(detail=NO_PENDING_UPLOAD_MESSAGE)


ERROR_RESPONSES = {
    400: OpenApiResponse(
        response=AgentTranscriptErrorSerializer,
        description="The file failed a check: wrong type, wrong size, not text, or it contains a credential.",
    ),
    409: OpenApiResponse(
        response=AgentTranscriptErrorSerializer,
        description="The submission's status does not allow this step.",
    ),
    503: OpenApiResponse(response=AgentTranscriptErrorSerializer, description="Object storage is unavailable."),
}


class _UploadThrottle(SimpleRateThrottle):
    """One bucket per organization, shared by both upload steps.

    The default throttles skip session requests, and members upload through the session. This is a plain
    `SimpleRateThrottle`, so it applies to them, and a second member of the organization gets no new budget.
    """

    def get_cache_key(self, request: Request, view: APIView) -> str:
        organization_id = PersonalApiKeyRateThrottle.safely_get_organization_id_from_view(view)
        ident = organization_id or (request.user.pk if request.user.is_authenticated else self.get_ident(request))
        return self.cache_format % {"scope": self.scope, "ident": ident}


class UploadBurstThrottle(_UploadThrottle):
    scope = "agent_transcript_upload_burst"
    rate = "10/minute"


class UploadSustainedThrottle(_UploadThrottle):
    scope = "agent_transcript_upload_sustained"
    rate = "40/day"


UPLOAD_ACTIONS = frozenset({"start_upload", "complete_upload"})


class AgentTranscriptViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """The organization's transcript of its signup conversation with an AI agent. Any member can submit it."""

    scope_object = "INTERNAL"

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action in UPLOAD_ACTIONS:
            return [*super().get_throttles(), UploadBurstThrottle(), UploadSustainedThrottle()]

        return super().get_throttles()

    @extend_schema(
        description="The organization's transcript submission as its members see it.",
        responses={200: CustomerSubmissionStateSerializer},
    )
    @action(detail=False, methods=["GET"])
    def submission(self, request: Request, **kwargs) -> Response:
        state = api.get_customer_state(self.organization.id)

        return Response(CustomerSubmissionStateSerializer(instance=state).data)

    @extend_schema(
        description="Step 1 of the upload: returns a presigned POST to send the transcript file to. The file "
        "goes straight to storage. Call complete_upload once the POST succeeds.",
        request=StartUploadRequestSerializer,
        responses={200: PresignedUploadSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["POST"])
    def start_upload(self, request: Request, **kwargs) -> Response:
        serializer = StartUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            presigned_upload = api.start_upload(
                StartUploadInput(
                    organization_id=self.organization.id,
                    filename=serializer.validated_data["filename"],
                    size_bytes=serializer.validated_data["size_bytes"],
                    agent=TranscriptAgent(serializer.validated_data["agent"]),
                )
            )
        except UploadRejected as rejection:
            raise _rejection_error(rejection)
        except InvalidSubmissionState as error:
            raise _conflict_error(error)
        except TranscriptStorageUnavailable:
            raise StorageUnavailable()

        return Response(PresignedUploadSerializer(instance=presigned_upload).data)

    @extend_schema(
        description="Step 2 of the upload: checks the uploaded file and sends it to review.",
        request=None,
        responses={200: CustomerSubmissionStateSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["POST"])
    def complete_upload(self, request: Request, **kwargs) -> Response:
        user = cast(User, request.user)

        try:
            state = api.complete_upload(
                CompleteUploadInput(
                    organization_id=self.organization.id,
                    user_id=user.id,
                    distinct_id=str(user.distinct_id),
                )
            )
        except UploadRejected as rejection:
            raise _rejection_error(rejection)
        except (InvalidSubmissionState, SubmissionNotFound):
            raise SubmissionConflict()
        except TranscriptStorageUnavailable:
            raise StorageUnavailable()

        return Response(CustomerSubmissionStateSerializer(instance=state).data)
