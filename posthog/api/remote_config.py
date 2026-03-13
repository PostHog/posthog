import re
import hashlib

from django.http import Http404, HttpResponse, JsonResponse

from opentelemetry import trace
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from posthog.models.remote_config import RemoteConfig
from posthog.models.snippet_versioning import DEFAULT_SNIPPET_VERSION

tracer = trace.get_tracer(__name__)


def add_vary_headers(response):
    """
    Add Vary headers for Origin and Referer to responses.
    """
    response["Vary"] = "Origin, Referer"
    return response


def compute_etag(content: str) -> str:
    return f'"{hashlib.sha256(content.encode()).hexdigest()[:16]}"'


def add_cache_headers(response, token: str, etag: str, snippet_version: str = DEFAULT_SNIPPET_VERSION):
    """Add caching headers for CDN-served array.js responses.

    ETag: content hash for conditional requests. Clients send If-None-Match
    on subsequent requests and get a 304 if the content hasn't changed,
    avoiding a full re-download.

    Cache-Control: serve from CDN cache for up to 1 hour (max-age=3600).
    After that, the CDN can still serve stale content for up to 24 hours
    (stale-while-revalidate=86400) while revalidating in the background.

    Cache-Tag: used for targeted CDN purges. Tags by requested version and
    token so we can invalidate at two granularities:
    - posthog-js-{snippet_version}: purge all responses for a given
      snippet version when a new version is published or yanked. Uses the
      snippet version (e.g. "1", "1.358"), not the resolved version, so
      only affected versions are purged.
    - token:{token}: purge all responses for a specific project (e.g.
      when a team changes their snippet version).
    """
    response["ETag"] = etag
    response["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=86400"
    response["Cache-Tag"] = f"posthog-js-{snippet_version}, token:{token}"
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

        requested_version = RemoteConfig.get_requested_snippet_version(token)
        response = HttpResponse(script_content, content_type="application/javascript")
        add_cache_headers(response, token, etag, snippet_version=requested_version)
        return add_vary_headers(response)
