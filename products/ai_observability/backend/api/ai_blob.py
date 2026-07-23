from django.conf import settings
from django.http import HttpResponse

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

INLINE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


class AIBlobViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    # llm_analytics (not INTERNAL) so resource-level access controls apply to blob reads.
    # Deliberately no scope_object_read_actions: the custom action then rejects API keys,
    # keeping this endpoint session-only for v1.
    scope_object = "llm_analytics"

    @extend_schema(exclude=True)
    @action(detail=False, methods=["GET"], url_path=r"v1/sha256/(?P<hash>[0-9a-f]{64})")
    def serve(self, request: Request, hash: str, **kwargs) -> HttpResponse:
        key = f"{settings.AI_BLOB_S3_PREFIX}{self.team_id}/sha256/{hash}"
        try:
            result = object_storage.read_object(key, bucket=settings.AI_BLOB_S3_BUCKET, missing_ok=True)
        except ObjectStorageError:
            # Storage is unreachable (e.g. missing credentials) or the read failed. read_object
            # already captured the exception, so degrade to a 503 rather than bubbling a 500 —
            # the blob may well exist, so a 404 would be misleading.
            return HttpResponse(status=503)
        if result is None:
            return HttpResponse(status=404)
        body, content_type = result
        if content_type in INLINE_MIMES:
            response = HttpResponse(body, content_type=content_type)
        else:
            response = HttpResponse(body, content_type="application/octet-stream")
            # Bare attachment: a filename here would override the frontend's `download` attribute.
            response["Content-Disposition"] = "attachment"
        response["Cache-Control"] = "private, max-age=86400, immutable"
        response["ETag"] = f'"{hash}"'
        response["X-Content-Type-Options"] = "nosniff"
        return response
