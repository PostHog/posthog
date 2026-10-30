from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.paging import Page, PageRequest

from products.cdp.backend.api.plugin import PluginsAccessLevelPermission
from products.cdp.backend.models.plugin import (
    PluginLogEntry,
    PluginLogEntryType,
    PluginLogFilters,
    count_plugin_log_entries,
    fetch_plugin_log_entries,
)


class PluginLogEntrySerializer(DataclassSerializer):
    class Meta:
        dataclass = PluginLogEntry


class PluginLogEntryPagination(FacadeLimitOffsetPagination):
    # `PluginLogEntryRequestSerializer.limit` uses these bounds, so it rejects a limit the paginator would cut.
    default_limit = 100


class PluginLogEntryRequestSerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=PluginLogEntryPagination.max_limit,
        help_text=(
            "Maximum number of log entries to return "
            f"(1-{PluginLogEntryPagination.max_limit}, default {PluginLogEntryPagination.default_limit})."
        ),
    )
    after = serializers.DateTimeField(required=False, help_text="Only return entries after this ISO 8601 timestamp.")
    before = serializers.DateTimeField(required=False, help_text="Only return entries before this ISO 8601 timestamp.")
    search = serializers.CharField(required=False, help_text="Case-insensitive substring search across log messages.")
    type_filter = serializers.ListField(
        child=serializers.ChoiceField(choices=PluginLogEntryType.choices),
        required=False,
        help_text="Log types to include. Repeat the parameter to include more than one type.",
    )


class PluginLogEntryViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "plugin"
    serializer_class = PluginLogEntrySerializer
    permission_classes = [PluginsAccessLevelPermission]
    pagination_class = PluginLogEntryPagination

    @extend_schema(parameters=[PluginLogEntryRequestSerializer])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        param_serializer = PluginLogEntryRequestSerializer(data=request.query_params)
        param_serializer.is_valid(raise_exception=True)
        params = param_serializer.validated_data

        filters = PluginLogFilters(
            team_id=self.team_id,
            plugin_config_id=self.parents_query_dict["plugin_config_id"],
            after=params.get("after"),
            before=params.get("before"),
            search=params.get("search"),
            type_filter=tuple(PluginLogEntryType[name] for name in params.get("type_filter", [])),
        )

        def fetch(page: PageRequest) -> Page[PluginLogEntry]:
            rows = fetch_plugin_log_entries(filters, limit=page.limit, offset=page.offset)
            # A short page is the last page, so it gives the total without a second scan. An empty page
            # past the first one gives no total, because the offset can be past the end.
            if len(rows) < page.limit and (rows or page.offset == 0):
                return Page(results=rows, count=page.offset + len(rows))
            return Page(results=rows, count=count_plugin_log_entries(filters))

        return facade_page_response(self, fetch)
