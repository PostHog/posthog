from io import BytesIO
from typing import Optional
from urllib.parse import quote

from django.conf import settings
from django.http import HttpResponse
from django.utils.http import content_disposition_header
from django.views.decorators.csrf import csrf_exempt

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_field
from PIL import Image, ImageOps
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, UnsupportedMediaType, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from statshog.defaults.django import statsd

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import UploadedMedia
from posthog.models.uploaded_media import ObjectStorageUnavailable
from posthog.storage import object_storage

FOUR_MEGABYTES = 4 * 1024 * 1024

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


# The set of image types the media library will actually sniff and serve. Deliberately
# narrower than the download route's inline-safe allowlist: no SVG (never safe to serve
# inline — script execution risk), no AVIF (Pillow build support is inconsistent).
_SNIFFABLE_IMAGE_CONTENT_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

# Guards against a decompression bomb: a small, highly-compressed file that decodes to an
# enormous bitmap. Checked from the header, before Pillow decodes the full image into memory.
_MAX_IMAGE_PIXELS = 50_000_000


def sniff_image_content_type(data: Optional[bytes]) -> Optional[str]:
    """Determine an image's real content type from its bytes — never trust a caller's claim.

    Returns None if the bytes don't decode as one of the image types the library
    supports, so the caller can reject rather than store or serve a claimed type
    that doesn't match the actual content.
    """
    if not data:
        return None
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            if width * height > _MAX_IMAGE_PIXELS:
                return None
            image.load()
            content_type = Image.MIME.get(image.format or "")
    except Exception:
        return None
    return content_type if content_type in _SNIFFABLE_IMAGE_CONTENT_TYPES else None


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

    if instance.pending:
        # Awaiting complete_upload — the bytes at media_location, if any, are unvetted.
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


class UploadedMediaSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="file_name", read_only=True, help_text="The file's original name.")
    url = serializers.SerializerMethodField(
        help_text="Permanent, public URL of the image. For emails, put this in an image block's values.src.url."
    )

    class Meta:
        model = UploadedMedia
        fields = ["id", "name", "purpose", "content_type", "size_bytes", "url", "created_at"]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.URI)
    def get_url(self, obj: UploadedMedia) -> str:
        return obj.get_absolute_url()


# How long a presigned upload URL stays valid. The caller (an agent's shell) is expected to
# upload within seconds of calling start_upload, so this is generous headroom, not a target.
UPLOAD_URL_EXPIRATION_SECONDS = 900


class UploadedMediaStartUploadSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=1000, help_text="The file's display name, e.g. 'logo.png'.")
    purpose = serializers.CharField(
        max_length=100, help_text="Library to add this image to once uploaded, e.g. 'email'."
    )


class UploadedMediaUploadStartedSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Id of the pending upload — pass this to complete_upload.")
    upload_url = serializers.URLField(read_only=True, help_text="POST the image file here as multipart/form-data.")
    form_fields = serializers.DictField(
        read_only=True, help_text="Extra form fields to send alongside the file in the same POST."
    )
    expires_in = serializers.IntegerField(read_only=True, help_text="Seconds before upload_url expires.")


class UploadedMediaCreateSerializer(serializers.Serializer):
    image = serializers.FileField(help_text="Image file. Must be under 4MB and a real, decodable image.")
    purpose = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Library to add this image to, e.g. `email`. Omit to upload without joining a library "
        "(as dashboard text cards and notebooks do).",
    )


@extend_schema(extensions={"x-product": "core"})
class MediaViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "uploaded_media"
    scope_object_write_actions = ["create", "start_upload", "complete_upload"]
    queryset = UploadedMedia.objects.all()
    serializer_class = _FallbackSerializer
    parser_classes = (MultiPartParser, FormParser)

    def safely_get_queryset(self, queryset):
        if self.action == "complete_upload":
            return queryset.filter(pending=True)
        return queryset.filter(pending=False).order_by("-created_at")

    @extend_schema(
        description="List images in the media library. Requires a `purpose` filter — the library is scoped per "
        "consumer (e.g. `email`), so browsing without one would mix in unrelated uploads (dashboard "
        "images, toolbar screenshots, ...).",
        parameters=[
            OpenApiParameter(
                name="purpose",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="The library to list, e.g. `email`.",
            )
        ],
        responses={200: UploadedMediaSerializer(many=True), 400: OpenApiResponse(description="Missing `purpose`.")},
    )
    def list(self, request, *args, **kwargs) -> Response:
        purpose = request.query_params.get("purpose")
        if not purpose:
            raise ValidationError(code="purpose_required", detail="A purpose query parameter is required.")
        queryset = self.get_queryset().filter(purpose=purpose)
        page = self.paginate_queryset(queryset)
        serializer = UploadedMediaSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        description="Step 1 of the presigned upload flow: reserves a pending image and returns a presigned URL "
        "to POST the file to directly, bytes never pass through this API. Call complete_upload with the "
        "returned id once the upload finishes.",
        request=UploadedMediaStartUploadSerializer,
        responses={
            201: UploadedMediaUploadStartedSerializer,
            400: OpenApiResponse(description="Missing `name`/`purpose`, or object storage is unavailable."),
        },
    )
    @action(methods=["POST"], detail=False, parser_classes=[JSONParser])
    def start_upload(self, request, *args, **kwargs) -> Response:
        serializer = UploadedMediaStartUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow media uploads.",
            )

        uploaded_media = UploadedMedia.objects.create(
            team=self.team,
            created_by=request.user,
            file_name=serializer.validated_data["name"],
            purpose=serializer.validated_data["purpose"],
            pending=True,
        )
        staging_location = UploadedMedia.build_staging_location(self.team_id, uploaded_media.pk)
        presigned_post = object_storage.get_presigned_post(
            staging_location,
            conditions=[["content-length-range", 1, FOUR_MEGABYTES]],
            expiration=UPLOAD_URL_EXPIRATION_SECONDS,
        )
        if not presigned_post:
            uploaded_media.delete()
            raise ValidationError(code="object_storage_required", detail="Could not create an upload URL.")

        uploaded_media.media_location = staging_location
        uploaded_media.save(update_fields=["media_location"])

        return Response(
            {
                "id": uploaded_media.id,
                "upload_url": presigned_post["url"],
                "form_fields": presigned_post["fields"],
                "expires_in": UPLOAD_URL_EXPIRATION_SECONDS,
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        description="Step 2 of the presigned upload flow: verifies the object POSTed to the upload_url, sniffs its "
        "real content type, and activates it — after this it appears in the library and is publicly "
        "servable.",
        request=None,
        responses={
            200: UploadedMediaSerializer,
            400: OpenApiResponse(description="The upload wasn't found, is too large, or isn't a valid image."),
            404: OpenApiResponse(description="No matching pending upload for this team."),
        },
    )
    @action(methods=["POST"], detail=True, parser_classes=[JSONParser])
    def complete_upload(self, request, *args, **kwargs) -> Response:
        uploaded_media = self.get_object()

        head = object_storage.head_object(uploaded_media.media_location)
        if head is None:
            raise ValidationError(code="upload_not_found", detail="No file was uploaded to the upload URL.")

        content_length = head.get("ContentLength")
        if not isinstance(content_length, int) or content_length > FOUR_MEGABYTES:
            raise ValidationError(code="file_too_large", detail="Uploaded media must be less than 4MB")

        content = object_storage.read_bytes(uploaded_media.media_location)
        sniffed_content_type = sniff_image_content_type(content)
        if sniffed_content_type is None:
            uploaded_media.delete()
            object_storage.delete(uploaded_media.media_location)
            raise ValidationError(code="invalid_image", detail="Uploaded media must be a valid image")

        # The presigned POST stays valid (and thus rewritable) until it expires — moving
        # the verified bytes to a key it was never signed for is what makes a later reuse
        # of that form harmless, rather than just re-checking on every future read.
        staging_location = uploaded_media.media_location
        permanent_location = UploadedMedia.build_media_location(self.team_id, uploaded_media.pk)
        object_storage.copy(staging_location, permanent_location)
        object_storage.delete(staging_location)

        uploaded_media.media_location = permanent_location
        uploaded_media.content_type = sniffed_content_type
        uploaded_media.size_bytes = content_length
        uploaded_media.pending = False
        uploaded_media.save(update_fields=["media_location", "content_type", "size_bytes", "pending"])

        statsd.incr(
            "uploaded_media.uploaded",
            tags={"team_id": self.team.pk, "content_type": sniffed_content_type},
        )
        return Response(UploadedMediaSerializer(uploaded_media).data)

    @extend_schema(
        description="""
    When object storage is available this API allows upload of media which can be used, for example, in text cards on dashboards.

    Uploaded media must have a content type beginning with 'image/' and be less than 4MB. Pass `purpose` to also
    add the image to a library (e.g. `email`), making it visible to `GET ?purpose=...`.
    """,
        request=UploadedMediaCreateSerializer,
        responses={201: OpenApiTypes.OBJECT},
    )
    def create(self, request, *args, **kwargs) -> Response:
        try:
            file = request.data["image"]
            purpose = request.data.get("purpose") or None

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

                # to save having to copy the stream so that we can read it to verify the image,
                # save it to minio anyway and then delete the record if it's not valid
                if uploaded_media.media_location is None:
                    raise APIException("Could not read uploaded media")
                bytes_to_verify = object_storage.read_bytes(uploaded_media.media_location)
                sniffed_content_type = sniff_image_content_type(bytes_to_verify)
                if sniffed_content_type is None:
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

                # Store what the bytes really are, never what the caller claimed.
                uploaded_media.content_type = sniffed_content_type
                uploaded_media.size_bytes = len(bytes_to_verify) if bytes_to_verify else None
                uploaded_media.purpose = purpose
                uploaded_media.save(update_fields=["content_type", "size_bytes", "purpose"])

                headers = self.get_success_headers(uploaded_media.get_absolute_url())
                statsd.incr(
                    "uploaded_media.uploaded",
                    tags={"team_id": self.team.pk, "content_type": sniffed_content_type},
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
            else:
                raise UnsupportedMediaType(file.content_type)
        except KeyError:
            raise ValidationError(code="no-image-provided", detail="An image file must be provided")
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
