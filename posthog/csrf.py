"""Fetch-metadata CSRF protection, for every entry point that checks CSRF.

`ModernCsrfViewMiddleware` decides on the `Sec-Fetch-Site` header the browser sets itself, so a
write no longer depends on a token surviving in the tab.

REST Framework marks every `APIView` CSRF-exempt and runs its own token check inside
`SessionAuthentication.enforce_csrf`, outside the middleware chain, so `/api/` is covered here
rather than by the middleware. That check reads `CSRFCheck` from its own module at call time, so
replacing the name covers every `SessionAuthentication` in the codebase — including the plain
REST Framework one that a dozen product viewsets declare directly, which overriding only our own
subclass would leave on tokens.
"""

from django.http import HttpRequest

import rest_framework.authentication
from modern_csrf.middleware import ModernCsrfViewMiddleware


class ModernCSRFCheck(ModernCsrfViewMiddleware):
    """Drop-in for `rest_framework.authentication.CSRFCheck`, which returns the rejection reason
    rather than rendering it."""

    def process_request(self, request: HttpRequest) -> None:
        """REST Framework calls this to load the cookie a token check needs. Nothing reads one."""

    def _reject(self, request: HttpRequest, reason: str) -> str:
        return reason


def install() -> None:
    rest_framework.authentication.CSRFCheck = ModernCSRFCheck  # type: ignore[misc] # ty: ignore[invalid-assignment]
