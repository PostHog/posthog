from typing import Any

from django.db.models import Q, QuerySet

from posthog.models.activity_logging.activity_log import ActivityLog


class AdvancedActivityLogFilterManager:
    def apply_filters(self, queryset: QuerySet[ActivityLog], filters: dict[str, Any]) -> QuerySet[ActivityLog]:
        queryset = self._apply_date_filters(queryset, filters)
        queryset = self._apply_user_filters(queryset, filters)
        queryset = self._apply_scope_filters(queryset, filters)
        queryset = self._apply_activity_filters(queryset, filters)
        queryset = self._apply_search_filters(queryset, filters)
        queryset = self._apply_detail_filters(queryset, filters.get("detail_filters", {}))
        queryset = self._apply_hogql_filter(queryset, filters.get("hogql_filter"))

        return queryset

    def _apply_date_filters(self, queryset: QuerySet[ActivityLog], filters: dict[str, Any]) -> QuerySet[ActivityLog]:
        if filters.get("start_date"):
            queryset = queryset.filter(created_at__gte=filters["start_date"])
        if filters.get("end_date"):
            queryset = queryset.filter(created_at__lte=filters["end_date"])
        return queryset

    def _apply_user_filters(self, queryset: QuerySet[ActivityLog], filters: dict[str, Any]) -> QuerySet[ActivityLog]:
        if filters.get("users"):
            queryset = queryset.filter(user_id__in=filters["users"])
        return queryset

    def _apply_scope_filters(self, queryset: QuerySet[ActivityLog], filters: dict[str, Any]) -> QuerySet[ActivityLog]:
        if filters.get("scopes"):
            queryset = queryset.filter(scope__in=filters["scopes"])
        return queryset

    def _apply_activity_filters(
        self, queryset: QuerySet[ActivityLog], filters: dict[str, Any]
    ) -> QuerySet[ActivityLog]:
        if filters.get("activities"):
            queryset = queryset.filter(activity__in=filters["activities"])
        return queryset

    def _apply_search_filters(self, queryset: QuerySet[ActivityLog], filters: dict[str, Any]) -> QuerySet[ActivityLog]:
        if filters.get("search_text"):
            search_query = Q(detail__icontains=filters["search_text"])
            queryset = queryset.filter(search_query)
        return queryset

    def _apply_detail_filters(
        self, queryset: QuerySet[ActivityLog], detail_filters: dict[str, Any]
    ) -> QuerySet[ActivityLog]:
        for field_path, filter_config in detail_filters.items():
            operation = filter_config.get("operation", "exact")
            value = filter_config.get("value")

            if operation == "exact":
                queryset = queryset.filter(**{f"detail__{field_path}": value})
            elif operation == "in":
                queryset = queryset.filter(**{f"detail__{field_path}__in": value})
            elif operation == "contains":
                queryset = queryset.filter(**{f"detail__{field_path}__icontains": value})

        return queryset

    def _apply_hogql_filter(self, queryset: QuerySet[ActivityLog], hogql_filter: str | None) -> QuerySet[ActivityLog]:
        """
        Apply HogQL filters
        TODO: (to be implemented in a later phase).
        """
        return queryset
