from typing import cast
from urllib.parse import urlencode, urlparse

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from posthog.api.utils import hostname_in_allowed_url_list
from posthog.constants import PERMITTED_FORUM_DOMAINS
from posthog.models import User
from posthog.utils import render_template

TOOLBAR_OAUTH_ERROR_PATH = "/toolbar_oauth/error"
TOOLBAR_OAUTH_ERROR_SESSION_KEY = "toolbar_oauth_error"


def redirect_to_toolbar_oauth_error(
    request: HttpRequest,
    *,
    title: str,
    message: str,
    status_code: int,
    detail: str | None = None,
    links_to_authorized_urls: bool = False,
) -> HttpResponse:
    """Redirect to the toolbar sign-in error page, which reads this error from the session.

    The refused request's URL can hold an unredeemed authorization code, the OAuth state, or a URL of the user's
    site. The error page loads the app, and the app's analytics and session replay record the page URL. So the
    error page has its own URL with no query string, and the error goes to it through the session.
    """
    request.session[TOOLBAR_OAUTH_ERROR_SESSION_KEY] = {
        "title": title,
        "message": message,
        "detail": detail,
        "links_to_authorized_urls": links_to_authorized_urls,
        "status_code": status_code,
    }
    return redirect(TOOLBAR_OAUTH_ERROR_PATH)


def toolbar_oauth_error(request: HttpRequest) -> HttpResponse:
    error = request.session.pop(TOOLBAR_OAUTH_ERROR_SESSION_KEY, None)
    if not error:
        return render_template("index.html", request)
    status_code = error.pop("status_code")
    return render_template("index.html", request, context={"toolbar_oauth_error": error}, status_code=status_code)


def authorize_and_redirect(request: HttpRequest) -> HttpResponse:
    if not request.GET.get("redirect"):
        return HttpResponse("You need to pass a url to ?redirect=", status=400)
    if not request.headers.get("referer"):
        return HttpResponse('You need to make a request that includes the "Referer" header.', status=400)

    current_team = cast(User, request.user).team
    referer_url = urlparse(request.headers["referer"])
    redirect_url = urlparse(request.GET["redirect"])
    is_forum_login = request.GET.get("forum_login", "").lower() == "true"

    if (
        not current_team
        or (redirect_url.hostname not in PERMITTED_FORUM_DOMAINS and is_forum_login)
        or (not is_forum_login and not hostname_in_allowed_url_list(current_team.app_urls, redirect_url.hostname))
    ):
        hostname = redirect_url.hostname or request.GET["redirect"]
        return redirect_to_toolbar_oauth_error(
            request,
            title="Domain not authorized",
            message="The toolbar cannot authenticate on this domain because it is not in your project's authorized URLs.",
            detail=(
                f"The hostname {hostname} needs to be added to your project's "
                "authorized URLs before the toolbar can be used on this site."
            ),
            links_to_authorized_urls=True,
            status_code=403,
        )

    if referer_url.hostname != redirect_url.hostname:
        return HttpResponse(
            f"Can only redirect to the same domain as the referer: {referer_url.hostname}",
            status=403,
        )

    if referer_url.scheme != redirect_url.scheme:
        return HttpResponse(
            f"Can only redirect to the same scheme as the referer: {referer_url.scheme}",
            status=403,
        )

    if referer_url.port != redirect_url.port:
        return HttpResponse(
            f"Can only redirect to the same port as the referer: {referer_url.port or 'no port in URL'}",
            status=403,
        )

    return render_template(
        "authorize_and_link.html" if is_forum_login else "authorize_and_redirect.html",
        request=request,
        context={
            "email": request.user,
            "domain": redirect_url.hostname,
            "redirect_url": request.GET["redirect"],
            "authorization_url": f"/api/user/redirect_to_site/?{urlencode({'appUrl': request.GET['redirect']})}",
        },
    )
