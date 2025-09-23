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
            queryset = queryset.filter(user__uuid__in=filters["users"])
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

            if value is None:
                continue

            if "[]" in field_path:
                # Array fields like changes[].type need special handling
                queryset = self._apply_array_field_filter(queryset, field_path, operation, value)
            else:
                django_field_path = field_path.replace(".", "__")
                if operation == "exact":
                    queryset = queryset.filter(**{f"detail__{django_field_path}": value})
                elif operation == "in":
                    if not isinstance(value, list | tuple):
                        value = [value]
                    queryset = queryset.filter(**{f"detail__{django_field_path}__in": value})
                elif operation == "contains":
                    queryset = queryset.filter(**{f"detail__{django_field_path}__icontains": value})

        return queryset

    def _apply_array_field_filter(
        self, queryset: QuerySet[ActivityLog], field_path: str, operation: str, value: Any
    ) -> QuerySet[ActivityLog]:
        if operation == "contains":
            queryset = self._apply_array_contains_filter(queryset, field_path, value)
        else:
            queryset = self._apply_array_exact_filter(queryset, field_path, operation, value)
        return queryset

    def _apply_array_contains_filter(
        self, queryset: QuerySet[ActivityLog], field_path: str, value: Any
    ) -> QuerySet[ActivityLog]:
        base_array_path = field_path.split("[]")[0]
        return queryset.filter(**{f"detail__{base_array_path}__icontains": value})

    def _apply_array_exact_filter(
        self, queryset: QuerySet[ActivityLog], field_path: str, operation: str, value: Any
    ) -> QuerySet[ActivityLog]:
        from django.db.models import Q

        parts = field_path.split("[].")
        if len(parts) < 2:
            return self._apply_array_contains_filter(queryset, field_path, value)

        max_indices_to_check = 5  # Check first 5 elements of each array
        query_conditions = []

        for i in range(max_indices_to_check):
            django_path = self._build_indexed_path(parts, [i])

            if operation == "exact":
                condition = Q(**{f"detail__{django_path}": value})
            elif operation == "in":
                if not isinstance(value, list | tuple):
                    value = [value]
                condition = Q(**{f"detail__{django_path}__in": value})
            else:
                continue

            query_conditions.append(condition)

        # Handle nested arrays like items[].data[].name
        if field_path.count("[]") > 1:
            for i in range(max_indices_to_check):
                for j in range(max_indices_to_check):
                    django_path = self._build_indexed_path(parts, [i, j])

                    if operation == "exact":
                        condition = Q(**{f"detail__{django_path}": value})
                    elif operation == "in":
                        if not isinstance(value, list | tuple):
                            value = [value]
                        condition = Q(**{f"detail__{django_path}__in": value})
                    else:
                        continue

                    query_conditions.append(condition)

        if field_path.count("[]") > 2:
            for i in range(max_indices_to_check):
                for j in range(max_indices_to_check):
                    for k in range(max_indices_to_check):
                        django_path = self._build_indexed_path(parts, [i, j, k])

                        if operation == "exact":
                            condition = Q(**{f"detail__{django_path}": value})
                        elif operation == "in":
                            if not isinstance(value, list | tuple):
                                value = [value]
                            condition = Q(**{f"detail__{django_path}__in": value})
                        else:
                            continue

                        query_conditions.append(condition)

        # Combine all conditions with OR
        if query_conditions:
            combined_query = query_conditions[0]
            for condition in query_conditions[1:]:
                combined_query |= condition
            return queryset.filter(combined_query)

        return queryset

    def _build_indexed_path(self, parts: list[str], indices: list[int]) -> str:
        if not parts or not indices:
            return ""

        result = parts[0]

        for i, index in enumerate(indices):
            if i + 1 < len(parts):
                result += f"__{index}__{parts[i + 1]}"
            else:
                result += f"__{index}"

        return result.replace(".", "__")

    def _convert_field_path_to_django_syntax(self, field_path: str) -> str:
        if "[]" in field_path:
            return field_path
        return field_path.replace(".", "__")

    def _apply_hogql_filter(self, queryset: QuerySet[ActivityLog], hogql_filter: str | None) -> QuerySet[ActivityLog]:
        # TODO: HogQL filtering to be implemented
        return queryset
