from typing import Dict

from django.http import FileResponse
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, PermissionDenied, UnsupportedMediaType
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import UploadedMedia
from posthog.storage import object_storage


class MediaViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    queryset = UploadedMedia.objects.all()
    parser_classes = (MultiPartParser, FormParser)

    def create(self, request, *args, **kwargs) -> Response:
        try:
            file = request.data["image"]
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

    def get_success_headers(self, location: str) -> Dict:
        try:
            return {"Location": location}
        except (TypeError, KeyError):
            return {}

    def retrieve(self, request, *args, **kwargs) -> FileResponse:
        if request.user.current_team != self.team:
            raise PermissionDenied()

        instance: UploadedMedia = self.get_object()

        file_bytes = object_storage.read_bytes(instance.media_location)
        return FileResponse(file_bytes, content_type=instance.content_type)
