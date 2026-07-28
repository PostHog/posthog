"""Spec-mandated error envelopes for the Stripe provisioning namespace.

APP 0.1d fixes three error shapes on the wire (plus a flat one used by the
signature/version checks), so DRF's default error rendering can never leak out
of these endpoints:

- ``typed``:  ``{"type": "error", "error": {...}}`` - account_requests, where
  ``type`` is the discriminator partners switch on ("oauth" | "error").
- ``status``: ``{"status": "error", "id": ..., "error": {...}}`` - resource
  endpoints, whose success envelope carries "status" and "id".
- ``oauth``:  RFC 6749 ``{"error", "error_description"}`` - the token endpoint.
- ``flat``:   ``{"error": {"code", "message"}}`` - signature / API-Version /
  region-proxy failures, identical on every endpoint.

Views raise :class:`SpecError`; the base view's ``handle_exception`` renders it
with the view's envelope (or the error's own override - rate-limit errors keep
the typed shape even on the token endpoint).
"""

from __future__ import annotations

from typing import Any, Literal

from rest_framework import status as http_status
from rest_framework.response import Response

Envelope = Literal["typed", "status", "oauth", "flat"]


class PreRenderedError(Exception):
    """Carries an already-rendered error Response through DRF's exception flow.

    The signature/version helpers return flat-envelope Responses; when those
    checks run in ``initial()`` (outside a handler) the only way to
    short-circuit is to raise, so this wraps the Response for the base view's
    ``handle_exception`` to unwrap unchanged.
    """

    def __init__(self, response: Response) -> None:
        super().__init__()
        self.response = response


class SpecError(Exception):
    """An error with a spec-defined code, message, and envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = http_status.HTTP_400_BAD_REQUEST,
        request_id: str | None = None,
        resource_id: str = "",
        envelope: Envelope | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.request_id = request_id
        self.resource_id = resource_id
        self.envelope = envelope
        self.retry_after = retry_after


def render_spec_error(error: SpecError, default_envelope: Envelope) -> Response:
    envelope = error.envelope or default_envelope
    body: dict[str, Any]
    if envelope == "typed":
        body = {"type": "error", "error": {"code": error.code, "message": error.message}}
        # "id" appears only when a request_id was threaded through; some call
        # sites carry "" (rendered as "id": "") and others no id at all.
        if error.request_id is not None:
            body = {"id": error.request_id, **body}
    elif envelope == "status":
        body = {"status": "error", "id": error.resource_id, "error": {"code": error.code, "message": error.message}}
    elif envelope == "oauth":
        body = {"error": error.code, "error_description": error.message}
    else:
        body = {"error": {"code": error.code, "message": error.message}}

    response = Response(body, status=error.status)
    if error.retry_after is not None:
        response["Retry-After"] = str(error.retry_after)
    return response
