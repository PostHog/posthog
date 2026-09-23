from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

_CONNECT_REDIRECT_ALLOWED_KINDS = {"github", "slack", "linear"}
# Surfaces allowed to start a connect flow and be returned to afterwards (see
# posthog/api/github_callback/types.py APP_CONNECT_FROM_VALUES, plus Slack).
_CONNECT_REDIRECT_ALLOWED_SURFACES = {"posthog_code", "posthog_mobile", "slack"}


def integration_connect_redirect(request: HttpRequest, kind: str) -> HttpResponse:
    """Login-gated entry point for starting an integration OAuth connect from an external surface
    (a Slack message, the desktop app, etc.). Wrapped in ``login_required`` so unauthenticated users
    are bounced to login and resume here, then redirected into the existing ``integrations/authorize``
    flow with a ``connect_from``-tagged return page. ``next`` is constructed internally (never taken
    from the query) so this can't be used as an open redirect."""
    if kind not in _CONNECT_REDIRECT_ALLOWED_KINDS:
        return HttpResponse("Unsupported integration kind", status=400)
    connect_from = request.GET.get("connect_from", "")
    if connect_from not in _CONNECT_REDIRECT_ALLOWED_SURFACES:
        return HttpResponse("Unsupported connect_from", status=400)
    project_id = request.GET.get("project_id") or getattr(request.user, "current_team_id", None)
    if not project_id or not str(project_id).isdigit():
        return HttpResponse("Missing or invalid project_id", status=400)

    next_path = "/account-connected/{}-integration?{}".format(
        kind, urlencode({"provider": kind, "project_id": project_id, "connect_from": connect_from})
    )
    authorize_url = "/api/projects/{}/integrations/authorize/?{}".format(
        project_id, urlencode({"kind": kind, "next": next_path})
    )
    return HttpResponseRedirect(authorize_url)
