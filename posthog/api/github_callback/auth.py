"""Authentication gates for GitHub callback entrypoints."""

from __future__ import annotations

from urllib.parse import quote

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect


def login_redirect(request: HttpRequest, *, resume_path: str) -> HttpResponseRedirect:
    return redirect(f"/login?next={quote(resume_path, safe='')}")


def require_session_or_login_redirect(
    request: HttpRequest,
    *,
    resume_path: str,
) -> HttpResponseRedirect | None:
    if request.user.is_authenticated:
        return None
    return login_redirect(request, resume_path=resume_path)


def require_session_or_401(request: HttpRequest) -> HttpResponse | None:
    if request.user.is_authenticated:
        return None
    return JsonResponse({"detail": "Authentication credentials were not provided."}, status=401)
