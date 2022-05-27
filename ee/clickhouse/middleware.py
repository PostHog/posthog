from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.urls.base import resolve
from loginas.utils import is_impersonated_session

from posthog.internal_metrics import incr


class CHQueries(object):
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        """ Install monkey-patch on demand.

        If monkey-patch has not been run in for this process (assuming multiple preforked processes),
        then do it now.

        """
        from posthog import client

        route = resolve(request.path)
        route_id = f"{route.route} ({route.func.__name__})"
        client._request_information = {
            "save": (request.user.pk and (request.user.is_staff or is_impersonated_session(request) or settings.DEBUG)),
            "user_id": request.user.pk,
            "kind": "request",
            "id": route_id,
        }

        response: HttpResponse = self.get_response(request)

        if "api/" in route_id and "capture" not in route_id:
            incr("http_api_request_response", tags={"id": route_id, "status_code": response.status_code})

        client._request_information = None

        return response
