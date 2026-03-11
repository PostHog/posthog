import re
import hashlib

from django.http import Http404, HttpResponse, JsonResponse

from opentelemetry import trace
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from posthog.models.remote_config import RemoteConfig

tracer = trace.get_tracer(__name__)


def add_vary_headers(response):
    """
    Add Vary headers for Origin and Referer to responses.
    """
    response["Vary"] = "Origin, Referer"
    return response


def compute_etag(content: str) -> str:
    return f'"{hashlib.sha256(content.encode()).hexdigest()[:16]}"'


def add_cache_headers(response, token: str, content: str, pin: str | None = None):
    """Add ETag, Cache-Control, and Cache-Tag headers."""
    response["ETag"] = compute_etag(content)
    response["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=86400"

    # Cache-Tag based on pin type
    if pin is None:
        version_tag = "posthog-js-latest"
    else:
        version_tag = f"posthog-js-{pin}" if not pin[0].isdigit() else f"posthog-js-v{pin}"

    response["Cache-Tag"] = f"{version_tag}, token:{token}"
    return response


class BaseRemoteConfigAPIView(APIView):
    """
    Base class for RemoteConfig API views.
    """

    authentication_classes = []
    permission_classes = []

    def check_token(self, token: str):
        # Most tokens are phc_xxx but there are some older ones that are random strings including underscores and dashes
        if len(token) > 200 or not re.match(r"^[a-zA-Z0-9_-]+$", token):
            raise ValidationError("Invalid token")
        return token


class RemoteConfigAPIView(BaseRemoteConfigAPIView):
    @tracer.start_as_current_span("RemoteConfig.APIView.get")
    def get(self, request, token: str, *args, **kwargs):
        try:
            resource = RemoteConfig.get_config_via_token(self.check_token(token), request=request)
        except RemoteConfig.DoesNotExist:
            raise Http404()

        return add_vary_headers(JsonResponse(resource))


class RemoteConfigJSAPIView(BaseRemoteConfigAPIView):
    @tracer.start_as_current_span("RemoteConfig.JSAPIView.get")
    def get(self, request, token: str, *args, **kwargs):
        try:
            script_content = RemoteConfig.get_config_js_via_token(self.check_token(token), request=request)
        except RemoteConfig.DoesNotExist:
            raise Http404()

        return add_vary_headers(HttpResponse(script_content, content_type="application/javascript"))


class RemoteConfigArrayJSAPIView(BaseRemoteConfigAPIView):
    @tracer.start_as_current_span("RemoteConfig.ArrayJSAPIView.get")
    def get(self, request, token: str, *args, **kwargs):
        token = self.check_token(token)

        try:
            script_content = RemoteConfig.get_array_js_via_token(token, request=request)
        except RemoteConfig.DoesNotExist:
            raise Http404()

        # Check ETag for 304 revalidation
        etag = compute_etag(script_content)
        if request.META.get("HTTP_IF_NONE_MATCH") == etag:
            response = HttpResponse(status=304)
            response["ETag"] = etag
            return add_vary_headers(response)

        pin = RemoteConfig.get_snippet_version_pin(token)

        response = HttpResponse(script_content, content_type="application/javascript")
        add_cache_headers(response, token, script_content, pin=pin)
        return add_vary_headers(response)
