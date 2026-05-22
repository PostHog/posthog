"""Dispatch GitHub App setup callbacks from GitHub-mandated entry URLs."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.views.decorators.http import require_http_methods

from posthog.api.github_callback import auth, finish, parse, redirects


@require_http_methods(["GET"])
def handle_setup_url(request: HttpRequest) -> HttpResponseRedirect:
    """GitHub App Setup URL — team finish or personal install (same router)."""
    resume_path = request.get_full_path()
    if redirect := auth.require_session_or_login_redirect(request, resume_path=resume_path):
        return redirect

    ctx = parse.parse_callback(request, "setup_url")
    result = finish.finish(request, ctx)
    return redirects.redirect_from_finish_result(result)


@require_http_methods(["GET"])
def handle_oauth_redirect(request: HttpRequest) -> HttpResponse | HttpResponseRedirect:
    """GitHub User OAuth redirect_uri — personal and team-oauth recovery flows."""
    if response := auth.require_session_or_401(request):
        return response

    ctx = parse.parse_callback(request, "oauth_redirect")
    result = finish.finish(request, ctx)
    return redirects.redirect_from_finish_result(result)
