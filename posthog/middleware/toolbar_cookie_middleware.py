from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware


class ToolbarCookieMiddleware(SessionMiddleware):
    def process_response(self, request, response):
        response = super().process_response(request, response)

        # skip adding the toolbar 3rd party cookie on API requests
        if request.path.startswith("/api/") or request.path.startswith("/e/") or request.path.startswith("/decide/"):
            return response

        toolbar_cookie_name = settings.TOOLBAR_COOKIE_NAME  # type: str
        toolbar_cookie_secure = settings.TOOLBAR_COOKIE_SECURE  # type: bool

        if (
            toolbar_cookie_name not in response.cookies
            and request.user
            and request.user.is_authenticated
            and request.user.toolbar_mode != "disabled"
        ):
            response.set_cookie(
                toolbar_cookie_name,  # key
                "yes",  # value
                365 * 24 * 60 * 60,  # max_age = one year
                None,  # expires
                "/",  # path
                None,  # domain
                toolbar_cookie_secure,  # secure
                True,  # httponly
                "Lax",  # samesite, can't be set to "None" here :(
            )
            response.cookies[toolbar_cookie_name]["samesite"] = "None"  # must set explicitly

        return response
