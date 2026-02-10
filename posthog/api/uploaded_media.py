from io import BytesIO
from typing import Optional

from django.core.files.uploadedfile import UploadedFile
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog
from drf_spectacular.utils import extend_schema
from PIL import Image
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, UnsupportedMediaType, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from statshog.defaults.django import statsd

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import TemporaryTokenAuthentication
from posthog.models import Team, UploadedMedia, User
from posthog.models.uploaded_media import ObjectStorageUnavailable
from posthog.storage import object_storage

FOUR_MEGABYTES = 4 * 1024 * 1024

logger = structlog.getLogger(__name__)


def validate_image_file(file: Optional[bytes], user: int) -> bool:
    """
    Django validates file content type by reading "magic bytes" from the start of the file.
    It doesn't then check that file really is the type it claims to be.

    This could allow an attacker to attempt to upload HTML with magic bytes that pretend to be an image file.
    We would store that and then serve it back to a dashboard. ☠️

    Here we check that the file is actually a valid image file by opening and transposing it.
    """
    if file is None:
        return False

    try:
        im = Image.open(BytesIO(file))
        im.transpose(Image.FLIP_LEFT_RIGHT)
        im.close()
        return True
    except Exception as e:
        logger.error(
            "uploaded_media.image_verification_error",
            user=user,
            exception=e,
            exc_info=True,
        )
        return False


def upload_image(
    team: Team,
    file: UploadedFile,
    created_by: Optional[User] = None,
    size_limit: int = FOUR_MEGABYTES,
) -> UploadedMedia:
    """
    Shared image upload logic for both authenticated and widget uploads.

    Validates size/content-type, saves to object storage, and verifies with PIL.
    Raises ValidationError, UnsupportedMediaType, or ObjectStorageUnavailable on failure.
    """
    if file.size is None or file.size > size_limit:
        raise ValidationError(
            code="file_too_large", detail=f"Uploaded media must be less than {size_limit // (1024 * 1024)}MB"
        )

    if not file.content_type or not file.content_type.startswith("image/"):
        raise UnsupportedMediaType(file.content_type or "unknown")

    uploaded_media = UploadedMedia.save_content(
        team=team,
        created_by=created_by,
        file_name=file.name or "unnamed",
        content_type=file.content_type,
        content=file.read(),
    )
    if uploaded_media is None or not uploaded_media.media_location:
        raise APIException("Could not save media")

    # Verify with PIL to prevent XSS via fake magic bytes
    bytes_to_verify = object_storage.read_bytes(uploaded_media.media_location)
    user_id = created_by.id if created_by else 0
    if not validate_image_file(bytes_to_verify, user=user_id):
        statsd.incr(
            "uploaded_media.image_failed_validation",
            tags={"file_name": file.name, "team": team.pk},
        )
        uploaded_media.delete()
        raise ValidationError(code="invalid_image", detail="Uploaded media must be a valid image")

    statsd.incr(
        "uploaded_media.uploaded",
        tags={"team_id": team.pk, "content_type": file.content_type},
    )
    return uploaded_media


@csrf_exempt
def download(request, *args, **kwargs) -> HttpResponse:
    """
    Images are immutable, so we can cache them forever
    They are served unauthenticated as they might be presented on shared dashboards
    """
    instance: Optional[UploadedMedia] = None
    try:
        instance = UploadedMedia.objects.get(pk=kwargs["image_uuid"])
    except UploadedMedia.DoesNotExist:
        return HttpResponse(status=404)

    file_bytes = object_storage.read_bytes(instance.media_location)

    statsd.incr(
        "uploaded_media.served",
        tags={"team_id": instance.team_id, "uuid": kwargs["image_uuid"]},
    )

    return HttpResponse(
        file_bytes,
        content_type=instance.content_type,
        headers={"Cache-Control": "public, max-age=315360000, immutable"},
    )


class MediaViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    queryset = UploadedMedia.objects.all()
    parser_classes = (MultiPartParser, FormParser)
    authentication_classes = [TemporaryTokenAuthentication]

    @extend_schema(
        description="""
    When object storage is available this API allows upload of media which can be used, for example, in text cards on dashboards.

    Uploaded media must have a content type beginning with 'image/' and be less than 4MB.
    """
    )
    def create(self, request, *args, **kwargs) -> Response:
        try:
            file = request.data["image"]
        except KeyError:
            raise ValidationError(code="no-image-provided", detail="An image file must be provided")

        try:
            uploaded_media = upload_image(team=self.team, file=file, created_by=request.user)
            headers = self.get_success_headers(uploaded_media.get_absolute_url())
            return Response(
                {
                    "id": uploaded_media.id,
                    "image_location": uploaded_media.get_absolute_url(),
                    "name": uploaded_media.file_name,
                },
                status=status.HTTP_201_CREATED,
                headers=headers,
            )
        except ObjectStorageUnavailable:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow media uploads.",
            )

    def get_success_headers(self, location: str) -> dict:
        try:
            return {"Location": location}
        except (TypeError, KeyError):
            return {}
