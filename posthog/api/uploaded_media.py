from typing import Dict

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, NotFound, UnsupportedMediaType, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.internal_metrics import incr
from posthog.models import UploadedMedia
from posthog.models.uploaded_media import ObjectStorageUnavailable
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.storage import object_storage

FOUR_MEGABYTES = 4 * 1024 * 1024


@csrf_exempt
def download(request, *args, **kwargs) -> HttpResponse:
    """
    Images are immutable, so we can cache them forever
    They are served unauthenticated as they might be presented on shared dashboards
    """
    instance: UploadedMedia = UploadedMedia.objects.get(pk=kwargs["image_uuid"])
    if not instance or not instance.file_name == kwargs["file_name"]:
        raise NotFound("Image not found")

    file_bytes = object_storage.read_bytes(instance.media_location)

    incr("uploaded_media.served", tags={"team_id": instance.team_id, "uuid": kwargs["image_uuid"]})

    return HttpResponse(
        file_bytes,
        content_type=instance.content_type,
        headers={"Cache-Control": "public, max-age=315360000, immutable"},
    )


class MediaViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    queryset = UploadedMedia.objects.all()
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [
        IsAuthenticatedOrReadOnly,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
    ]

    @extend_schema(
        description="""
    When object storage is available this API allows upload of media which can be used, for example, in text cards on dashboards.

    Uploaded media must have a content type beginning with 'image/' and be less than 4MB.
    """
    )
    def create(self, request, *args, **kwargs) -> Response:
        try:
            file = request.data["image"]

            if file.size > FOUR_MEGABYTES:
                raise ValidationError(code="file_too_large", detail="Uploaded media must be less than 4MB")

            if file.content_type.startswith("image/"):
                uploaded_media = UploadedMedia.save_content(
                    team=self.team,
                    created_by=request.user,
                    file_name=file.name,
                    content_type=file.content_type,
                    content=file.file,
                )
                if uploaded_media is None:
                    raise APIException("Could not save media")
                headers = self.get_success_headers(uploaded_media.get_absolute_url())
                incr("uploaded_media.uploaded", tags={"team_id": self.team.pk, "content_type": file.content_type})
                return Response(
                    {
                        "id": uploaded_media.id,
                        "image_location": uploaded_media.get_absolute_url(),
                        "name": uploaded_media.file_name,
                    },
                    status=status.HTTP_201_CREATED,
                    headers=headers,
                )
            else:
                raise UnsupportedMediaType(file.content_type)
        except KeyError:
            raise ValidationError(code="no-image-provided", detail="An image file must be provided")
        except ObjectStorageUnavailable:
            raise ValidationError(
                code="object_storage_required", detail="Object storage must be available to allow media uploads."
            )

    def get_success_headers(self, location: str) -> Dict:
        try:
            return {"Location": location}
        except (TypeError, KeyError):
            return {}
