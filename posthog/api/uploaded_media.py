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

# Non-image content types accepted by the upload endpoint. These are never
# rendered inline — download() serves them as forced downloads — so they can be
# attached to support tickets without the stored-XSS risk that HTML/SVG carry.
# This is a deliberate safe allowlist, not an open door: executables, scripts,
# HTML, and SVG stay blocked because they are the types that turn a download
# into a foot-gun. PDFs are byte-checked; the plain-text types cannot be
# meaningfully sniffed and don't need to be, since they only ever download.
_UPLOADABLE_DOCUMENT_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "text/plain",
        "text/markdown",
        "text/x-markdown",
        "text/csv",
        "application/csv",
    }
)

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


def validate_pdf_file(file: Optional[bytes]) -> bool:
    """Verify the bytes really are a PDF before we store them under a PDF content
    type. PDFs are served as forced downloads, so this guards against a spoofed
    content type being persisted, not against inline execution."""
    if file is None:
        return False
    return file[:5] == b"%PDF-"


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
    When object storage is available this API allows upload of media which can be used, for example, in text cards on dashboards or as attachments on support tickets.

    Uploaded media must be less than 4MB and one of a safe allowlist: an image (content type beginning with 'image/'), a PDF, or a plain-text document ('text/plain', 'text/markdown', 'text/csv'). Non-image types are always served as downloads.
    """,
        responses={201: OpenApiTypes.OBJECT},
    )
    def create(self, request, *args, **kwargs) -> Response:
        try:
            file = request.data["image"]

            if file.size > FOUR_MEGABYTES:
                raise ValidationError(code="file_too_large", detail="Uploaded media must be less than 4MB")

            content_type = _normalize_content_type(file.content_type)
            is_image = content_type.startswith("image/")
            if not is_image and content_type not in _UPLOADABLE_DOCUMENT_CONTENT_TYPES:
                raise UnsupportedMediaType(file.content_type)

            uploaded_media = UploadedMedia.save_content(
                team=self.team,
                created_by=request.user,
                file_name=file.name,
                content_type=file.content_type,
                content=file.file,
            )
            if uploaded_media is None:
                raise APIException("Could not save media")

            # to save having to copy the stream so that we can read it to verify the file,
            # save it to object storage anyway and then delete the record if it's not valid
            if uploaded_media.media_location is None:
                raise APIException("Could not read uploaded media")
            bytes_to_verify = object_storage.read_bytes(uploaded_media.media_location)
            if is_image:
                is_valid = validate_image_file(bytes_to_verify, user=request.user.id)
            elif content_type == "application/pdf":
                is_valid = validate_pdf_file(bytes_to_verify)
            else:
                # Remaining allowlisted types are plain text, served only as forced
                # downloads, so there's nothing to sniff or spoof into something unsafe.
                is_valid = True
            if not is_valid:
                statsd.incr(
                    "uploaded_media.image_failed_validation",
                    tags={"file_name": file.name, "team": self.team_id},
                )
                # TODO a batch process can delete media with no records in the DB or for deleted teams
                uploaded_media.delete()
                raise ValidationError(
                    code="invalid_file",
                    detail="Uploaded media must be a valid image, PDF, or text file",
                )

            headers = self.get_success_headers(uploaded_media.get_absolute_url())
            statsd.incr(
                "uploaded_media.uploaded",
                tags={"team_id": self.team.pk, "content_type": file.content_type},
            )
            return Response(
                {
                    "id": uploaded_media.id,
                    "image_location": uploaded_media.get_absolute_url(),
                    "name": uploaded_media.file_name,
                },
                status=status.HTTP_201_CREATED,
                headers=headers,
            )
        except KeyError:
            raise ValidationError(code="no-image-provided", detail="A file must be provided")
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
