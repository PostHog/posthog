"""Error envelopes for the agentic provisioning API.

The provisioning views serve three distinct wire contracts, so DRF's default
error rendering can never leak out of these endpoints:

- ``typed``:  ``{"type": "error", "error": {...}}`` — account requests and
  GitHub grants, where "type" is the discriminator partners switch on
  ("oauth" | "requires_auth" | "registering" | "error").
- ``status``: ``{"status": "error", "id": ..., "error": {...}}`` — the
  resource endpoints, whose success envelope carries "status" (provisioning
  state) and "id" (the partner's resource ID), so errors mirror that.
- ``oauth``:  RFC 6749 ``{"error", "error_description"}`` — the token endpoint.

(The region proxy runs before DRF rendering exists, so it serializes
``provisioning_error_body`` itself. Its ``proxy_failed`` 502 keeps a flat
``{"error": {"code", "message"}}`` shape of its own.)

Collapsing them would break partner clients that branch on "status" vs "type".
Views raise :class:`ProvisioningError`; the base view's ``handle_exception``
renders it with the view's envelope (or the error's own override — e.g. a
partner rate limit raised inside the OAuth token exchange keeps the typed
shape).
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from rest_framework import status as http_status
from rest_framework.response import Response

logger = structlog.get_logger(__name__)

Envelope = Literal["typed", "status", "oauth"]


class ProvisioningError(Exception):
    """An error with a wire-contract code, message, and envelope."""

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
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.request_id = request_id
        self.resource_id = resource_id
        self.envelope = envelope
        self.retry_after = retry_after
        # Structured detail merged alongside the error in the typed envelope, for failures
        # whose whole value is the detail (client_registration reports per-check results).
        self.extra = extra


def provisioning_error_body(error: ProvisioningError, default_envelope: Envelope) -> dict[str, Any]:
    """The wire body for an error, without a DRF response around it, so the region
    proxy can render errors before DRF's renderers exist."""
    envelope = error.envelope or default_envelope
    body: dict[str, Any]
    if envelope == "typed":
        body = {"type": "error", "error": {"code": error.code, "message": error.message}}
        if error.extra:
            body.update(error.extra)
        # "id" appears only when a request_id was threaded through; some call
        # sites carry "" (rendered as "id": "") and others no id at all.
        if error.request_id is not None:
            body = {"id": error.request_id, **body}
    elif envelope == "status":
        logger.warning(
            "provisioning.error_response",
            code=error.code,
            message=error.message,
            resource_id=error.resource_id,
            status=error.status,
        )
        body = {"status": "error", "id": error.resource_id, "error": {"code": error.code, "message": error.message}}
    else:
        body = {"error": error.code, "error_description": error.message}

    return body


def render_provisioning_error(error: ProvisioningError, default_envelope: Envelope) -> Response:
    response = Response(provisioning_error_body(error, default_envelope), status=error.status)
    if error.retry_after is not None:
        response["Retry-After"] = str(error.retry_after)
    return response
