from typing import Optional

from django.db.models import QuerySet

from rest_framework import serializers, viewsets, mixins
from rest_framework.pagination import PageNumberPagination, CursorPagination, BasePagination


from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import ActivityLog, NotificationViewed


class ActivityLogSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer()
    unread = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        exclude = ["team_id"]

    def get_unread(self, obj: ActivityLog) -> bool:
        """is the date of this log item newer than the user's bookmark"""
        if "user" not in self.context:
            return False

        user_bookmark: Optional[NotificationViewed] = NotificationViewed.objects.filter(
            user=self.context["user"]
        ).first()

        if user_bookmark is None:
            return True
        else:
            # API call from browser only includes milliseconds but python datetime in created_at includes microseconds
            bookmark_date = user_bookmark.last_viewed_activity_date
            return bookmark_date < obj.created_at.replace(microsecond=obj.created_at.microsecond // 1000 * 1000)


class ActivityLogPagination(BasePagination):
    def __init__(self):
        self.page_number_pagination = PageNumberPagination()
        self.cursor_pagination = CursorPagination()
        self.page_number_pagination.page_size = 100
        self.page_number_pagination.page_size_query_param = "page_size"
        self.page_number_pagination.max_page_size = 1000
        self.cursor_pagination.page_size = 100
        self.cursor_pagination.ordering = "-created_at"

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        if request.query_params.get("page"):
            return self.page_number_pagination.paginate_queryset(queryset, request, view)
        else:
            return self.cursor_pagination.paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        if self.request and self.request.query_params.get("page"):
            return self.page_number_pagination.get_paginated_response(data)
        else:
            return self.cursor_pagination.get_paginated_response(data)


class ActivityLogViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet, mixins.ListModelMixin):
    scope_object = "activity_log"
    queryset = ActivityLog.objects.all()
    serializer_class = ActivityLogSerializer
    pagination_class = ActivityLogPagination
    filter_rewrite_rules = {"project_id": "team_id"}

    def safely_get_queryset(self, queryset) -> QuerySet:
        params = self.request.GET.dict()

        if params.get("user"):
            queryset = queryset.filter(user=params.get("user"))
        if params.get("scope"):
            queryset = queryset.filter(scope=params.get("scope"))
        if params.get("scopes", None):
            scopes = str(params.get("scopes", "")).split(",")
            queryset = queryset.filter(scope__in=scopes)
        if params.get("item_id"):
            queryset = queryset.filter(item_id=params.get("item_id"))

        if params.get("page"):
            queryset = queryset.order_by("-created_at")

        return queryset
