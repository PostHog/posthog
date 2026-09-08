"""Machine-readable classification of Django's CSRF rejection reasons.

Django words its rejections as prose, and the wording changes between releases, so a client that
matches on the message breaks silently. These codes travel in the DRF error body instead, and they
split the rejections by whether a fresh token fixes them:

- ``csrf_token_invalid``: the CSRF cookie is missing, malformed, or does not match the submitted
  token. A tab produces this once the cookie outlives the session, because only a document render
  refreshes it. The client recovers by fetching a new token and repeating the request.
- ``csrf_origin_rejected``: the Origin or Referer is not trusted. That is a deployment or proxy
  problem, so no client-side retry resolves it.
"""

from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import (
    REASON_BAD_ORIGIN,
    REASON_BAD_REFERER,
    REASON_INSECURE_REFERER,
    REASON_MALFORMED_REFERER,
    REASON_NO_REFERER,
)
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET

CSRF_TOKEN_INVALID_CODE = "csrf_token_invalid"
CSRF_ORIGIN_REJECTED_CODE = "csrf_origin_rejected"

# How REST Framework words a rejection: `'CSRF Failed: %s' % reason` in
# rest_framework.authentication.SessionAuthentication.enforce_csrf.
DRF_CSRF_FAILURE_PREFIX = "CSRF Failed: "

# Django interpolates the offending Origin or Referer into these reasons, so only the fixed leading
# text can be matched. Cutting each template at its placeholder keeps the prefixes tied to Django's
# own constants instead of to copies that can drift out of sync.
_ORIGIN_REJECTION_PREFIXES: tuple[str, ...] = tuple(
    reason.split("%s")[0]
    for reason in (
        REASON_BAD_ORIGIN,
        REASON_BAD_REFERER,
        REASON_NO_REFERER,
        REASON_MALFORMED_REFERER,
        REASON_INSECURE_REFERER,
    )
)


def csrf_failure_code(reason: str) -> str:
    """Classify a Django CSRF rejection reason. Anything that is not an Origin or Referer rejection
    concerns the token itself, so it is reported as recoverable — a new token is cheap to issue, and
    a client that retries once and fails surfaces the error exactly as it does today."""
    if reason.startswith(_ORIGIN_REJECTION_PREFIXES):
        return CSRF_ORIGIN_REJECTED_CODE
    return CSRF_TOKEN_INVALID_CODE


@require_GET
@never_cache
@ensure_csrf_cookie
def csrf_token_view(request: HttpRequest) -> HttpResponse:
    """Reissue the CSRF cookie, so a tab whose cookie expired can repeat a request instead of
    dead-ending. Rendering the app document was the only way to get one.

    Deliberately unauthenticated. The cookie is the secret the submitted token has to match, so
    issuing one proves nothing and grants nothing, which is why every login page can carry one.
    The body is empty because the client reads the token from the cookie it just got."""
    return HttpResponse(status=204)
