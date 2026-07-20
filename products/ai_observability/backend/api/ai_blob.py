from django.conf import settings
from django.http import HttpResponse

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.storage import object_storage

INLINE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


class AIBlobViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    @extend_schema(exclude=True)
    @action(detail=False, methods=["GET"], url_path=r"v1/sha256/(?P<hash>[0-9a-f]{64})")
    def serve(self, request: Request, hash: str, **kwargs) -> HttpResponse:
        key = f"{settings.AI_BLOB_S3_PREFIX}{self.team_id}/sha256/{hash}"
        result = object_storage.read_object(key, bucket=settings.AI_BLOB_S3_BUCKET, missing_ok=True)
        if result is None:
            return HttpResponse(status=404)
        body, content_type = result
        if content_type in INLINE_MIMES:
            response = HttpResponse(body, content_type=content_type)
        else:
            response = HttpResponse(body, content_type="application/octet-stream")
            # Bare attachment: a filename here would override the frontend's `download` attribute.
            response["Content-Disposition"] = "attachment"
        # Content-addressed: the hash IS the content, so the asset is immutable forever.
        response["Cache-Control"] = "private, max-age=31536000, immutable"
        response["ETag"] = f'"{hash}"'
        response["X-Content-Type-Options"] = "nosniff"
        return response
