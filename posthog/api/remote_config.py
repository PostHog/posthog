import re

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse

from opentelemetry import trace
from prometheus_client import Counter
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from posthog.models.js_snippet_versioning import DEFAULT_SNIPPET_VERSION
from posthog.models.remote_config import ArrayJSObservers, RemoteConfig

ARRAY_JS_CONFIG_SOURCE_COUNTER = Counter(
    "posthog_array_js_config_source",
    "Origin config source used to serve /array/{token}/array.js.",
    labelnames=["source"],
)

ARRAY_JS_CONTENT_SOURCE_COUNTER = Counter(
    "posthog_array_js_content_source",
    "Origin JS artifact source used to serve /array/{token}/array.js.",
    labelnames=["source"],
)

ARRAY_JS_MANIFEST_SOURCE_COUNTER = Counter(
    "posthog_array_js_manifest_source",
    "Manifest source used while resolving snippet versions for /array/{token}/array.js.",
    labelnames=["source"],
)

tracer = trace.get_tracer(__name__)


def _observe_array_js_config_source(source: str) -> None:
    ARRAY_JS_CONFIG_SOURCE_COUNTER.labels(source=source).inc()


def _observe_array_js_content_source(source: str) -> None:
    ARRAY_JS_CONTENT_SOURCE_COUNTER.labels(source=source).inc()


def _observe_array_js_manifest_source(source: str) -> None:
    ARRAY_JS_MANIFEST_SOURCE_COUNTER.labels(source=source).inc()


def add_vary_headers(response):
    """
    Add Vary headers for Origin and Referer to responses.
    """
    response["Vary"] = "Origin, Referer"
    return response


def add_config_cache_headers(response):
    """Add Cache-Control header for config and config.js responses.

    These endpoints are served through multiple origins (assets CDN,
    proxy-direct, and the main ingestion endpoint). Only the assets CDN
    adds cache-control headers at the proxy layer. Without this header,
    browsers fall back to heuristic caching and may hold stale config
    for hours or days, causing SDK settings (recording conditions,
    feature flags, sampling rates) to stop updating.
    """
    response["Cache-Control"] = "public, max-age=300"
    return add_vary_headers(response)


def add_cache_headers(response, token: str, etag: str, snippet_version: str = DEFAULT_SNIPPET_VERSION):
    """Add caching and Vary headers for CDN-served array.js responses.

    ETag: content hash for conditional requests. Clients send If-None-Match
    on subsequent requests and get a 304 if the content hasn't changed,
    avoiding a full re-download.

    Cache-Control: serve from CDN cache for up to 1 hour (max-age).
    Version publishes and yanks actively purge via Cache-Tag, so max-age
    is mainly protecting origin from traffic volume, not freshness.
    After max-age expires, the CDN serves stale content for up to 24 hours
    (stale-while-revalidate) while revalidating in the background. If the
    origin returns an error, the CDN continues serving stale content for
    up to 24 hours (stale-if-error) instead of forwarding the error.
    All values are configurable via POSTHOG_JS_CDN_* env vars.

    Cache-Tag: used for targeted CDN purges. Tags by requested version and
    token so we can invalidate at two granularities:
    - posthog-js-{snippet_version}: purge all responses for a given
      snippet version when a new version is published or yanked. Uses the
      snippet version (e.g. "1", "1.358"), not the resolved version, so
      only affected versions are purged.
    - token:{token}: purge all responses for a specific project (e.g.
      when a team changes their snippet version).

    Vary: Origin, Referer — included here so callers don't need to
    remember to also call add_vary_headers separately.
    """
    response["ETag"] = etag
    max_age = settings.POSTHOG_JS_CDN_MAX_AGE
    swr = settings.POSTHOG_JS_CDN_STALE_WHILE_REVALIDATE
    sie = settings.POSTHOG_JS_CDN_STALE_IF_ERROR
    response["Cache-Control"] = f"public, max-age={max_age}, stale-while-revalidate={swr}, stale-if-error={sie}"
    response["Cache-Tag"] = f"posthog-js-{snippet_version}, token:{token}"
    return add_vary_headers(response)


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

        return add_config_cache_headers(JsonResponse(resource))


class RemoteConfigJSAPIView(BaseRemoteConfigAPIView):
    @tracer.start_as_current_span("RemoteConfig.JSAPIView.get")
    def get(self, request, token: str, *args, **kwargs):
        try:
            script_content = RemoteConfig.get_config_js_via_token(self.check_token(token), request=request)
        except RemoteConfig.DoesNotExist:
            raise Http404()

        return add_config_cache_headers(HttpResponse(script_content, content_type="application/javascript"))


class RemoteConfigArrayJSAPIView(BaseRemoteConfigAPIView):
    @tracer.start_as_current_span("RemoteConfig.ArrayJSAPIView.get")
    def get(self, request, token: str, *args, **kwargs):
        token = self.check_token(token)
        observers = ArrayJSObservers(
            config_source=_observe_array_js_config_source,
            manifest_source=_observe_array_js_manifest_source,
            js_content_source=_observe_array_js_content_source,
        )
        prepared = RemoteConfig.prepare_array_js_response(
            token,
            if_none_match=request.META.get("HTTP_IF_NONE_MATCH"),
            observers=observers,
        )
        if prepared.is_missing:
            raise Http404()

        meta = prepared.metadata
        assert meta is not None

        if prepared.not_modified:
            response = HttpResponse(status=304)
            return add_cache_headers(response, token, meta.etag, snippet_version=meta.requested_version)

        content = RemoteConfig.build_array_js_content(
            token,
            meta.config,
            meta.resolved_version,
            request=request,
            js_content_source_observer=observers.js_content_source,
        )
        response = HttpResponse(content, content_type="application/javascript")
        return add_cache_headers(response, token, meta.etag, snippet_version=meta.requested_version)
