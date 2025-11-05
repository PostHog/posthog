import json

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from rest_framework import status
from statshog.defaults.django import statsd

from posthog.exceptions import generate_exception_response
from posthog.exceptions_capture import capture_exception
from posthog.logging.timing import timed
from posthog.plugins.site import get_site_config_from_schema, get_transpiled_site_source


@csrf_exempt
@timed("posthog_cloud_site_app_endpoint")
def get_site_app(request: HttpRequest, id: int, token: str, hash: str) -> HttpResponse:
    try:
        source_file = get_transpiled_site_source(id, token) if token else None
        if not source_file:
            raise Exception("No source file found")

        id = source_file.id
        source = source_file.source
        config = get_site_config_from_schema(source_file.config_schema, source_file.config)
        response = f"{source}().inject({{config:{json.dumps(config)},posthog:window['__$$ph_site_app_{id}']}})"

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
