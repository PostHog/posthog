import json

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.exceptions import generate_exception_response
from posthog.logging.timing import timed
from posthog.plugins.web import get_transpiled_web_source, get_web_config_from_schema


@csrf_exempt
@timed("posthog_cloud_web_js_endpoint")
def get_web_js(request: HttpRequest, id: int, token: str):
    try:
        source_file = get_transpiled_web_source(id, token) if token else None
        if not source_file:
            raise Exception("No source file found")

        id = source_file.id
        source = source_file.source
        config = get_web_config_from_schema(source_file.config_schema, source_file.config)
        response = f"{source}().inject({{config:{json.dumps(config)},posthog:window['__$$ph_web_js_{id}']}})"

        statsd.incr(f"posthog_cloud_raw_endpoint_success", tags={"endpoint": "web_js"})
        return HttpResponse(content=response, content_type="application/javascript")
    except Exception as e:
        capture_exception(e, {"data": {"id": id, "token": token}})
        statsd.incr("posthog_cloud_raw_endpoint_failure", tags={"endpoint": "web_js"})
        return generate_exception_response(
            "web_js",
            "Unable to serve app source code.",
            code="missing_web_js_source",
            type="server_error",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
