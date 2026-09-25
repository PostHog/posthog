from django.db.models import Q, QuerySet

import django_filters
from rest_framework import response, serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request

from ee.api.scim.utils import mask_email, mask_string
from ee.models.scim_request_log import SCIMRequestLog


class SCIMRequestLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = SCIMRequestLog
        fields = (
            "id",
            "request_method",
            "request_path",
            "request_headers",
            "request_body",
            "response_status",
            "response_body",
            "identity_provider",
            "duration_ms",
            "created_at",
        )
        read_only_fields = fields


class PaginatedSCIMRequestLogSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Total number of matching SCIM requests.")
    next = serializers.URLField(allow_null=True, help_text="URL for the next page, or null on the last page.")
    previous = serializers.URLField(allow_null=True, help_text="URL for the previous page, or null on the first page.")
    results = SCIMRequestLogSerializer(many=True, help_text="SCIM requests on this page.")


class SCIMRequestLogQuerySerializer(serializers.Serializer):
    status_min = serializers.IntegerField(
        required=False, help_text="Minimum HTTP response status to include, such as 400."
    )
    status_max = serializers.IntegerField(
        required=False, help_text="Maximum HTTP response status to include, such as 499."
    )
    search = serializers.CharField(required=False, help_text="Search request paths and masked request bodies.")
    after = serializers.DateTimeField(required=False, help_text="Include requests at or after this time.")
    before = serializers.DateTimeField(required=False, help_text="Include requests at or before this time.")
    page = serializers.IntegerField(required=False, min_value=1, help_text="Page number to return.")
    page_size = serializers.IntegerField(
        required=False, min_value=1, max_value=100, help_text="Number of requests to return per page."
    )


class SCIMRequestLogPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _looks_like_email(value: str) -> bool:
    return "@" in value and "." in value.rpartition("@")[2]


def _search_scim_logs(queryset: QuerySet[SCIMRequestLog], _name: str, value: str) -> QuerySet[SCIMRequestLog]:
    query = Q(request_path__icontains=value) | Q(request_body__icontains=value)
    if _looks_like_email(value):
        query |= Q(request_body__icontains=mask_email(value))
    else:
        masked = mask_string(value)
        if masked != value:
            query |= Q(request_body__icontains=masked)
    return queryset.filter(query)


class SCIMRequestLogFilter(django_filters.FilterSet):
    status_min = django_filters.NumberFilter(field_name="response_status", lookup_expr="gte")
    status_max = django_filters.NumberFilter(field_name="response_status", lookup_expr="lte")
    search = django_filters.CharFilter(method="filter_search")
    after = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    before = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = SCIMRequestLog
        fields: list[str] = []

    def filter_search(self, queryset: QuerySet[SCIMRequestLog], name: str, value: str) -> QuerySet[SCIMRequestLog]:
        return _search_scim_logs(queryset, name, value)


def paginated_scim_request_logs_response(request: Request, queryset: QuerySet[SCIMRequestLog]) -> response.Response:
    filtered_queryset = SCIMRequestLogFilter(request.query_params, queryset=queryset).qs
    paginator = SCIMRequestLogPagination()
    page = paginator.paginate_queryset(filtered_queryset, request)
    serializer = SCIMRequestLogSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)
