"""Error-envelope helpers for the agentic provisioning API.

Two helpers coexist because the provisioning views serve two distinct wire
contracts (plus OAuth endpoints, which follow RFC 6749's flat
{"error", "error_description"} shape and can't use either helper):

- `error_response` -> {"status": "error", "id": ..., "error": {...}} for the
  resource endpoints, whose success envelope carries "status" (provisioning state)
  and "id" (the partner's resource ID), so errors mirror that.
- `typed_error_response` -> {"type": "error", "error": {...}} for account
  requests and GitHub grants, where "type" is the discriminator partners switch
  on ("oauth" | "registering" | "error").

Collapsing them would break partner clients that branch on "status" vs "type".
"""

from __future__ import annotations

from typing import Any

import structlog
from rest_framework.response import Response

logger = structlog.get_logger(__name__)


def error_response(code: str, message: str, resource_id: str = "", status: int = 400) -> Response:
    logger.warning("provisioning.error_response", code=code, message=message, resource_id=resource_id, status=status)
    return Response({"status": "error", "id": resource_id, "error": {"code": code, "message": message}}, status=status)


def typed_error_response(code: str, message: str, request_id: str | None = None, status: int = 400) -> Response:
    # No blanket warning log here: call sites already emit their own telemetry
    # (_capture_provisioning_event / logger.warning) at the right granularity.
    body: dict[str, Any] = {"type": "error", "error": {"code": code, "message": message}}
    if request_id is not None:
        body = {"id": request_id, **body}
    return Response(body, status=status)
