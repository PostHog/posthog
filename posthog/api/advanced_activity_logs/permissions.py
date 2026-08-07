import json
from typing import Optional

from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.permissions import PremiumFeaturePermission

from .constants import BILLING_EXEMPT_SCOPES


def _parse_scopes_param(raw_values: list[str]) -> set[str]:
    """Widest reading of a `scopes` query param, across every encoding the list endpoints accept.

    Depending on the endpoint and client, `scopes` arrives as repeated params, a JSON-encoded array,
    or a comma-separated string. Reading all three at once can only over-collect, which is the safe
    direction for the paywall decision below.
    """
    scopes: set[str] = set()
    for raw in raw_values:
        value = raw.strip()
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                parsed = None
            if isinstance(parsed, list):
                scopes.update(str(item) for item in parsed)
                continue
        scopes.update(part for part in (piece.strip() for piece in value.split(",")) if part)
    return scopes


def requested_scopes_are_billing_exempt(request: Request) -> bool:
    """Whether a request can only reach activity from scopes that are free on every plan.

    The list endpoints AND their `scope` and `scopes` filters together, so intersecting them here
    keeps the answer no wider than the rows the request can actually return. A request with no scope
    filter asks for the whole log, which is the paid feature, so it is never exempt.
    """
    reachable: Optional[set[str]] = None

    scope = request.query_params.get("scope")
    if scope:
        reachable = {scope}

    scopes = _parse_scopes_param(request.query_params.getlist("scopes"))
    if scopes:
        reachable = scopes if reachable is None else reachable & scopes

    if not reachable:
        return False

    return reachable <= BILLING_EXEMPT_SCOPES


class ActivityLogPremiumFeaturePermission(PremiumFeaturePermission):
    """Paywalls the activity log, except for requests narrowed to the always-free scopes.

    Feature flag and experiment history are part of those products rather than of the paid activity
    log, so a request filtered down to those scopes skips the feature check entirely.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        if requested_scopes_are_billing_exempt(request):
            return True
        return super().has_permission(request, view)
