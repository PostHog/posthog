import re

from django.http import HttpRequest, HttpResponse, JsonResponse

# Paths always allowed for guests — identity, auth, account settings, static/boot assets.
ALWAYS_ALLOWED_PATTERNS: list[re.Pattern] = [
    re.compile(r"^/api/users/@me/?$"),
    re.compile(r"^/api/users/@me/two_factor.*$"),
    re.compile(r"^/api/users/@me/password/?$"),
    re.compile(r"^/api/organizations/@current/?$"),
    re.compile(r"^/api/projects/@current/?$"),
    re.compile(r"^/api/environments/@current/?$"),
    re.compile(r"^/login/?$"),
    re.compile(r"^/logout/?$"),
    re.compile(r"^/api/login/?$"),
    re.compile(r"^/api/logout/?$"),
    re.compile(r"^/reset(/.*)?$"),
    re.compile(r"^/signup/verify_email(/.*)?$"),
    re.compile(r"^/_preflight/?$"),
    re.compile(r"^/static/.*$"),
    re.compile(r"^/favicon\.ico$"),
]


class GuestDeflectionMiddleware:
    """
    Deflects guest users from every endpoint not on an explicit allowlist.
    Runs after `AuthenticationMiddleware` but before `ActiveOrganizationMiddleware` — same
    slot family as the impersonation middlewares.

    Defense-in-depth with the access-control layer: AC short-circuits guests on
    resources it covers; this middleware covers surfaces AC does not (Data Warehouse,
    Logs, Error Tracking, Experiments, Feature Flags, Cohorts, etc.).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not self._user_is_guest(request):
            return self.get_response(request)

        if self._is_always_allowed(request.path):
            return self.get_response(request)

        # Conditionally-allowed (grant-bound) paths land in Task 2. For the scaffold,
        # unknown paths deflect.
        return self._deflect(request)

    def _user_is_guest(self, request: HttpRequest) -> bool:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        return user.organization_memberships.filter(is_guest=True).exists()

    def _is_always_allowed(self, path: str) -> bool:
        return any(p.match(path) for p in ALWAYS_ALLOWED_PATTERNS)

    def _deflect(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith("/api/"):
            return JsonResponse({"detail": "Not found"}, status=404)
        # SPA route → redirect to the guest landing (/guest). Frontend PR #3 renders it.
        from django.shortcuts import redirect

        return redirect("/guest")
