from urllib.parse import urlparse

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
)


def cors_response(request, response):
    if not request.headers.get("origin"):
        return response
    url = urlparse(request.headers["origin"])
    if url.netloc == "":
        response["Access-Control-Allow-Origin"] = "*"
    else:
        response["Access-Control-Allow-Origin"] = f"{url.scheme}://{url.netloc}"
    response["Access-Control-Allow-Credentials"] = "true"
    response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"

    # Handle headers that sentry randomly sends for every request.
    # Would cause a CORS failure otherwise.
    # specified here to override the default added by the cors headers package in web.py
    allow_headers = request.headers.get("access-control-request-headers", "").split(",")
    allow_headers = [header for header in allow_headers if header in CORS_ALLOWED_TRACING_HEADERS]

    response["Access-Control-Allow-Headers"] = "X-Requested-With,Content-Type" + (
        "," + ",".join(allow_headers) if len(allow_headers) > 0 else ""
    )
    return response
