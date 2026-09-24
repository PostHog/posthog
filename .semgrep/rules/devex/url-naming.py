# Test cases for the url-naming rules.
# ruff: noqa


class ExampleViewSet:
    # ruleid: api-path-underscore
    @action(methods=["POST"], detail=True, url_path="add-snapshots")
    def add_snapshots(self, request, **kwargs): ...

    # ruleid: api-path-underscore
    @action(methods=["GET"], detail=False, url_path="channel-pages/(?P<channel_id>[^/.]+)")
    def channel_pages(self, request, **kwargs): ...

    # ruleid: api-path-underscore
    @action(methods=["GET"], detail=False, url_path=r"(?P<run_id>[^/.]+)/check-result")
    def check_result(self, request, **kwargs): ...

    # ruleid: api-path-underscore
    @decorators.action(methods=["GET"], detail=False, url_path="sso-callback")
    def sso_callback(self, request, **kwargs): ...

    # ok: api-path-underscore
    @action(methods=["POST"], detail=True, url_path="add_snapshots")
    def add_snapshots_ok(self, request, **kwargs): ...

    # A hyphen inside a regex character class is not a literal segment.
    # ok: api-path-underscore
    @action(methods=["GET"], detail=False, url_path=r"api/v1/(?P<path>[A-Za-z0-9_./-]+)")
    def proxy(self, request, **kwargs): ...

    # ok: api-path-underscore
    @action(methods=["GET"], detail=False)
    def bulk_state(self, request, **kwargs): ...

    # nosemgrep: api-path-underscore
    @action(methods=["POST"], detail=True, url_path="cancel-deletion")
    def cancel_deletion(self, request, **kwargs): ...

    def list(self, request, **kwargs):
        # ruleid: api-query-param-underscore
        request.query_params.get("date-from")
        # ruleid: api-query-param-underscore
        request.GET.get("no-cache", False)
        # ruleid: api-query-param-underscore
        request.query_params["date-to"]
        # ruleid: api-query-param-underscore
        request.query_params.getlist("event-names")
        # ruleid: api-query-param-underscore
        request.GET.getlist("event-names")
        # ok: api-query-param-underscore
        request.query_params.get("date_from")
        # ok: api-query-param-underscore
        request.headers.get("X-Request-Id")


# ruleid: api-query-param-underscore
OpenApiParameter("date-from", OpenApiTypes.STR)
# ruleid: api-query-param-underscore
OpenApiParameter(name="date-to", type=OpenApiTypes.STR)
# ok: api-query-param-underscore
OpenApiParameter(name="date_to", type=OpenApiTypes.STR)
# ok: api-query-param-underscore
OpenApiParameter(name="X-Request-Id", type=OpenApiTypes.STR, location=OpenApiParameter.HEADER)
# ok: api-query-param-underscore
OpenApiParameter("X-Request-Id", str, OpenApiParameter.HEADER)


def register_routes(routers):
    # ruleid: api-path-underscore
    routers.environments.register(r"sandbox-pricing", SandboxPricingViewSet, "sandbox_pricing")
    # ruleid: api-path-underscore
    routers.projects.register(r"error_tracking/git-provider-file-links", LinksViewSet, "links")
    # ok: api-path-underscore
    routers.projects.register(r"error_tracking/symbol_sets", SymbolSetViewSet, "symbol_sets")
