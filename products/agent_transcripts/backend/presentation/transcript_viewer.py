"""The PostHog Admin page that shows a stored transcript as a readable agent session."""

from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from loginas.utils import is_impersonated_session

from posthog.csp_middleware import admit_admin_bundle

from ..facade import api
from ..facade.contracts import TranscriptStorageUnavailable

TRANSCRIPT_SOURCE = "transcript"


def transcript_viewer(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    """The React page for GET without `source`, and the transcript as JSON for `?source=transcript`."""
    if not request.user.is_active or not request.user.is_staff or is_impersonated_session(request):
        raise PermissionDenied

    if request.GET.get("source") != TRANSCRIPT_SOURCE:
        return admit_admin_bundle(
            render(
                request,
                "agent_transcript_viewer.html",
                {"js_url": settings.JS_URL, "organization_id": str(organization_id)},
            )
        )

    try:
        transcript = api.read_transcript(organization_id)
    except TranscriptStorageUnavailable:
        return JsonResponse({"detail": "Couldn't reach file storage. Try again in a few minutes."}, status=502)

    if transcript is None:
        return JsonResponse({"detail": "The transcript file is gone, or this organization has none."}, status=404)

    return JsonResponse({"agent": transcript.agent.value, "filename": transcript.filename, "text": transcript.text})
