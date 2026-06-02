from typing import Optional

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from posthog.api.uploaded_media import _is_inline_safe_content_type
from posthog.models.organization_custom_asset import OrganizationCustomAsset
from posthog.storage import object_storage


@csrf_exempt
def download(request, *args, **kwargs) -> HttpResponse:
    """
    Organization custom assets are immutable, so we can cache them forever.
    They are served unauthenticated as they brand the org UI and may appear before auth resolves —
    mirroring the /uploaded_media endpoint used for org logos.
    """
    instance: Optional[OrganizationCustomAsset] = None
    try:
        # Intentionally public lookup by id (mirrors uploaded_media) - assets brand the org UI.
        # nosemgrep: idor-lookup-without-org, idor-taint-user-input-to-org-model
        instance = OrganizationCustomAsset.objects.get(pk=kwargs["asset_uuid"])
    except (OrganizationCustomAsset.DoesNotExist, ValidationError):
        return HttpResponse(status=404)

    if instance.media_location is None:
        return HttpResponse(status=404)
    file_bytes = object_storage.read_bytes(instance.media_location)

    # Defense in depth against stored XSS: files whose content type is not on an inline-safe
    # allowlist (raster images) are served as an opaque download with a generic content type so
    # any malicious HTML/SVG/JS can't execute in the application origin — even if it slipped past
    # upload validation. See posthog.api.uploaded_media.download for the shared rationale.
    response_headers: dict[str, str] = {
        "Cache-Control": "public, max-age=315360000, immutable",
    }

    if _is_inline_safe_content_type(instance.content_type):
        response_content_type = instance.content_type
    else:
        response_content_type = "application/octet-stream"
        response_headers["Content-Disposition"] = "attachment"

    return HttpResponse(
        file_bytes,
        content_type=response_content_type,
        headers=response_headers,
    )
