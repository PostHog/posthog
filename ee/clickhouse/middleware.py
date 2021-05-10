from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.urls.base import resolve
from loginas.utils import is_impersonated_session

from posthog.ee import is_ee_enabled


class CHQueries(object):
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        """ Install monkey-patch on demand.

        If monkey-patch has not been run in for this process (assuming multiple preforked processes),
        then do it now.

        """
        from ee.clickhouse import client

        route = resolve(request.path)
        client._request_information = {
            "save": (
                is_ee_enabled()
                and request.user.pk
                and (request.user.is_staff or is_impersonated_session(request) or settings.DEBUG)
            ),
            "user_id": request.user.pk,
            "kind": "request",
            "id": f"{route.route} ({route.func.__name__})",
        }

        response: HttpResponse = self.get_response(request)

        client._request_information = None

        return response
