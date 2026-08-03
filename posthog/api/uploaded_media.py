import os
from io import BytesIO
from typing import Optional
from urllib.parse import quote

from django.http import HttpResponse
from django.utils.http import content_disposition_header
from django.views.decorators.csrf import csrf_exempt

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from PIL import Image, ImageOps
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, UnsupportedMediaType, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from statshog.defaults.django import statsd

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import UploadedMedia
from posthog.models.uploaded_media import ObjectStorageUnavailable
from posthog.storage import object_storage

FOUR_MEGABYTES = 4 * 1024 * 1024
TEN_MEGABYTES = 10 * 1024 * 1024

# Document types accepted alongside images, for surfaces that attach files rather
# than embed them (support ticket replies). These are never rendered inline — the
# download endpoint serves anything outside _INLINE_SAFE_CONTENT_TYPES as an
# opaque attachment — so the list only needs to cover what people actually send.
_DOCUMENT_EXTENSION_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
_ALLOWED_DOCUMENT_CONTENT_TYPES = frozenset(_DOCUMENT_EXTENSION_CONTENT_TYPES.values())

# Content types safe to render inline in a browser when served from the
# unauthenticated /uploaded_media endpoint. Anything outside this set is
# served as a download with a generic content type so stored HTML/SVG/etc.
# cannot execute script in the application origin.
_INLINE_SAFE_CONTENT_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/gif",
        "image/webp",
        "image/avif",
        "image/bmp",
    }
)

logger = structlog.getLogger(__name__)


def _normalize_content_type(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def _is_inline_safe_content_type(content_type: str | None) -> bool:
    return _normalize_content_type(content_type) in _INLINE_SAFE_CONTENT_TYPES


def _resolve_document_content_type(file_name: str | None, content_type: str) -> str | None:
    """Pick the content type to store for a document, or None if it isn't an allowed one.

    Browsers report Office files and CSVs inconsistently — a .docx often arrives as
    application/zip or application/octet-stream depending on what the OS has registered —
    so the extension gets a say, and what it maps to is what we store.
    """
    if content_type in _ALLOWED_DOCUMENT_CONTENT_TYPES:
        return content_type
    extension = os.path.splitext(file_name or "")[1].lower()
    return _DOCUMENT_EXTENSION_CONTENT_TYPES.get(extension)


def _attachment_disposition(file_name: str | None) -> str:
    """Build a Content-Disposition header that preserves the original filename.

    Without an explicit filename the browser falls back to the URL's last path
    segment — here the media UUID — so downloads lose their name and extension.

    file_name is attacker-influenced (inbound email/Slack attachments), so strip
    control characters (defends against CR/LF header injection) before encoding.
    Non-ASCII names get a quote-escaped ASCII ``filename`` fallback for legacy
    browsers alongside the RFC 5987 ``filename*`` parameter.
    """
    if not file_name:
        return "attachment"

    cleaned = "".join(ch for ch in file_name if ch.isprintable()).strip()
    if not cleaned:
        return "attachment"

    try:
        cleaned.encode("ascii")
        return content_disposition_header(as_attachment=True, filename=cleaned) or "attachment"
    except UnicodeEncodeError:
        ascii_fallback = cleaned.encode("ascii", "ignore").decode().strip() or "download"
        escaped = ascii_fallback.replace("\\", "\\\\").replace('"', '\\"')
        return f"attachment; filename=\"{escaped}\"; filename*=UTF-8''{quote(cleaned, safe='')}"


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
        ImageOps.mirror(im)
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


@csrf_exempt
def download(request, *args, **kwargs) -> HttpResponse:
    """
    Images are immutable, so we can cache them forever
    They are served unauthenticated as they might be presented on shared dashboards
    """
    instance: Optional[UploadedMedia] = None
    try:
        # nosemgrep: idor-lookup-without-team, idor-taint-user-input-to-model-get (intentionally public endpoint)
        instance = UploadedMedia.objects.get(pk=kwargs["image_uuid"])
    except UploadedMedia.DoesNotExist:
        return HttpResponse(status=404)

    if instance.media_location is None:
        return HttpResponse(status=404)
    file_bytes = object_storage.read_bytes(instance.media_location, missing_ok=True)
    if file_bytes is None:
        # The DB record exists but the underlying object-storage key is gone, so
        # there's nothing to serve — return a clean 404 rather than a 500.
        return HttpResponse(status=404)

    statsd.incr(
        "uploaded_media.served",
        tags={"team_id": instance.team_id, "uuid": kwargs["image_uuid"]},
    )

    # Defense in depth against stored XSS: files whose content type is not on
    # an inline-safe allowlist (raster images) are served as an opaque download
    # with a generic content type so any malicious HTML/SVG/JS can't execute
    # in the application origin — even if it slipped past upload validation.
    # CSPMiddleware layers on `default-src 'none'` for all non-HTML responses,
    # and SecurityMiddleware already emits X-Content-Type-Options: nosniff.
    response_headers: dict[str, str] = {
        "Cache-Control": "public, max-age=315360000, immutable",
    }

    if _is_inline_safe_content_type(instance.content_type):
        response_content_type = instance.content_type
    else:
        response_content_type = "application/octet-stream"
        response_headers["Content-Disposition"] = _attachment_disposition(instance.file_name)

    return HttpResponse(
        file_bytes,
        content_type=response_content_type,
        headers=response_headers,
    )


class MediaViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "uploaded_media"
    queryset = UploadedMedia.objects.all()
    serializer_class = _FallbackSerializer
    parser_classes = (MultiPartParser, FormParser)

    @extend_schema(
        description="""
    When object storage is available this API allows upload of media which can be used, for example, in text cards on dashboards.

    Send the file as `image` to only allow images, or as `file` to also allow documents (PDF, plain text, CSV and Office formats).

    Images must have a content type beginning with 'image/' and be less than 4MB. Documents must be less than 10MB.
    """,
        responses={201: OpenApiTypes.OBJECT},
    )
    def create(self, request, *args, **kwargs) -> Response:
        try:
            # `image` is the long-standing field and stays image-only; `file` additionally
            # accepts the document types we allow as attachments.
            documents_allowed = "file" in request.data
            file = request.data["file"] if documents_allowed else request.data["image"]

            content_type = _normalize_content_type(file.content_type)
            is_image = content_type.startswith("image/")
            if not is_image:
                document_content_type = (
                    _resolve_document_content_type(file.name, content_type) if documents_allowed else None
                )
                if document_content_type is None:
                    raise UnsupportedMediaType(file.content_type)
                content_type = document_content_type

            size_limit = FOUR_MEGABYTES if is_image else TEN_MEGABYTES
            if file.size > size_limit:
                raise ValidationError(
                    code="file_too_large",
                    detail=f"Uploaded media must be less than {size_limit // (1024 * 1024)}MB",
                )

            uploaded_media = UploadedMedia.save_content(
                team=self.team,
                created_by=request.user,
                file_name=file.name,
                content_type=content_type,
                content=file.file,
            )
            if uploaded_media is None:
                raise APIException("Could not save media")

            if uploaded_media.media_location is None:
                raise APIException("Could not read uploaded media")

            if is_image:
                # to save having to copy the stream so that we can read it to verify the image,
                # save it to minio anyway and then delete the record if it's not valid
                bytes_to_verify = object_storage.read_bytes(uploaded_media.media_location)
                if not validate_image_file(bytes_to_verify, user=request.user.id):
                    statsd.incr(
                        "uploaded_media.image_failed_validation",
                        tags={"file_name": file.name, "team": self.team_id},
                    )
                    # TODO a batch process can delete media with no records in the DB or for deleted teams
                    uploaded_media.delete()
                    raise ValidationError(
                        code="invalid_image",
                        detail="Uploaded media must be a valid image",
                    )

            headers = self.get_success_headers(uploaded_media.get_absolute_url())
            statsd.incr(
                "uploaded_media.uploaded",
                tags={"team_id": self.team.pk, "content_type": content_type},
            )
            return Response(
                {
                    "id": uploaded_media.id,
                    "image_location": uploaded_media.get_absolute_url(),
                    "name": uploaded_media.file_name,
                    "content_type": uploaded_media.content_type,
                },
                status=status.HTTP_201_CREATED,
                headers=headers,
            )
        except KeyError:
            raise ValidationError(code="no-image-provided", detail="An image or file must be provided")
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
