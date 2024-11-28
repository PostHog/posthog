from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.exceptions import generate_exception_response
from posthog.logging.timing import timed
from posthog.plugins.site import get_site_app_script


@csrf_exempt
@timed("posthog_cloud_site_app_endpoint")
def get_site_app(request: HttpRequest, id: int, token: str, hash: str) -> HttpResponse:
    try:
        response = get_site_app_script(id, token)
        statsd.incr(f"posthog_cloud_raw_endpoint_success", tags={"endpoint": "site_app"})
        return HttpResponse(content=response, content_type="application/javascript")
    except Exception as e:
        capture_exception(e, {"data": {"id": id, "token": token}})
        statsd.incr("posthog_cloud_raw_endpoint_failure", tags={"endpoint": "site_app"})
        return generate_exception_response(
            "site_app",
            "Unable to serve site app source code.",
            code="missing_site_app_source",
            type="server_error",
            status_code=status.HTTP_404_NOT_FOUND,
        )
