from typing import Dict

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, UnsupportedMediaType, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import UploadedMedia
from posthog.models.uploaded_media import ObjectStorageUnavailable
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.storage import object_storage


@csrf_exempt
def download(request, *args, **kwargs) -> HttpResponse:
    """
    Why is this on a top level route with no auth?
    img request wasn't sending cookies for some reason so we can't use auth
    and these images are immutable so we can cache them forever
    """
    instance: UploadedMedia = UploadedMedia.objects.get(pk=kwargs["image_uuid"])

    file_bytes = object_storage.read_bytes(instance.media_location)
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

    def create(self, request, *args, **kwargs) -> Response:
        try:
            file = request.data["image"]

            if file.size > 4 * 1024 * 1024:
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
            return Response("file missing.", status=status.HTTP_400_BAD_REQUEST)
        except ObjectStorageUnavailable:
            raise ValidationError(
                code="object_storage_required", detail="Object storage must be available to allow media uploads."
            )

    def get_success_headers(self, location: str) -> Dict:
        try:
            return {"Location": location}
        except (TypeError, KeyError):
            return {}
