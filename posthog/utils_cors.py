from urllib.parse import urlparse
from django.http import HttpRequest, HttpResponse
import structlog

logger = structlog.get_logger(__name__)

CORS_ALLOWED_TRACING_HEADERS = (
    "traceparent",
    "request-id",
    "request-context",
    "x-amzn-trace-id",
    "x-cloud-trace-context",
    "Sentry-Trace",
    "Baggage",
    "x-highlight-request",
    "x-datadome-clientid",
    "x-posthog-token",
    "x-b3-sampled",
    "x-b3-spanid",
    "x-b3-traceid",
    "x-b3-parentspanid",
    "b3",
)

# Temporary list of known good origins for monitoring
KNOWN_ORIGINS = {
    "app.posthog.com",
    "us.posthog.com",
    "eu.posthog.com",
    "localhost:8000",
    "localhost:8010",
    "app.dev.posthog.dev",
}


def cors_response(request: HttpRequest, response: HttpResponse) -> HttpResponse:
    """
    Returns a HttpResponse with CORS headers set to allow all origins.
    Only use this for endpoints that get called by the PostHog JS SDK.
    """
    if not request.META.get("HTTP_ORIGIN"):
        return response
    url = urlparse(request.META["HTTP_ORIGIN"])
    if url.netloc == "":
        response["Access-Control-Allow-Origin"] = "*"
        logger.info("cors_empty_netloc", path=request.path, method=request.method)
    else:
        response["Access-Control-Allow-Origin"] = f"{url.scheme}://{url.netloc}"
        # Log unknown origins for monitoring
        if url.netloc not in KNOWN_ORIGINS:
            logger.info(
                "cors_unknown_origin",
                origin=url.netloc,
                path=request.path,
                method=request.method,
                referer=request.META.get("HTTP_REFERER"),
                user_agent=request.META.get("HTTP_USER_AGENT"),
            )

    response["Access-Control-Allow-Credentials"] = "true"
    response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"

    # Handle headers that sentry randomly sends for every request.
    # Would cause a CORS failure otherwise.
    # specified here to override the default added by the cors headers package in web.py
    allow_headers = request.META.get("HTTP_ACCESS_CONTROL_REQUEST_HEADERS", "").split(",")
    allow_headers = [header for header in allow_headers if header in CORS_ALLOWED_TRACING_HEADERS]

    response["Access-Control-Allow-Headers"] = "X-Requested-With,Content-Type" + (
        "," + ",".join(allow_headers) if len(allow_headers) > 0 else ""
    )
    response["Vary"] = "Origin"
    return response
