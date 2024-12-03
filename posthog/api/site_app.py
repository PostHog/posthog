import json

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.exceptions import generate_exception_response
from posthog.logging.timing import timed
from posthog.models.hog_functions.hog_function import HogFunction
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


@csrf_exempt
@timed("posthog_cloud_site_app_endpoint")
def get_site_function(request: HttpRequest, id: str, hash: str) -> HttpResponse:
    try:
        # TODO: Should we add a token as well? Is the UUID enough?
        function = (
            HogFunction.objects.filter(
                id=id, enabled=True, type__in=("site_destination", "site_app"), transpiled__isnull=False
            )
            .values_list("transpiled")
            .first()
        )
        if not function:
            raise Exception("No function found")

        response = HttpResponse(content=function[0], content_type="application/javascript")
        response["Cache-Control"] = "public, max-age=31536000"  # Cache for 1 year
        statsd.incr(f"posthog_cloud_raw_endpoint_success", tags={"endpoint": "site_function"})
        return response
    except Exception as e:
        capture_exception(e, {"data": {"id": id}})
        statsd.incr("posthog_cloud_raw_endpoint_failure", tags={"endpoint": "site_function"})
        return generate_exception_response(
            "site_function",
            "Unable to serve site function source code.",
            code="missing_site_function_source",
            type="server_error",
            status_code=status.HTTP_404_NOT_FOUND,
        )
