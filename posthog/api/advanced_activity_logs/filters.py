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
        queryset = self._apply_was_impersonated_filter(queryset, filters)
        queryset = self._apply_is_system_filter(queryset, filters)
        queryset = self._apply_item_ids_filter(queryset, filters)
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
                django_field_path = f"detail__{field_path.replace('.', '__')}"
                query_condition = self._create_type_insensitive_query(django_field_path, operation, value)
                queryset = queryset.filter(query_condition)

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
        parts = field_path.split("[].")
        if len(parts) < 2:
            return self._apply_array_contains_filter(queryset, field_path, value)

        max_indices_to_check = 5  # Check first 5 elements of each array
        query_conditions = []

        indexed_paths = self._generate_indexed_paths(parts, field_path, max_indices_to_check)

        for django_path in indexed_paths:
            query_condition = self._create_type_insensitive_query(f"detail__{django_path}", operation, value)
            query_conditions.append(query_condition)

        # Combine all conditions with OR
        if query_conditions:
            combined_query = query_conditions[0]
            for condition in query_conditions[1:]:
                combined_query |= condition
            return queryset.filter(combined_query)

        return queryset

    def _generate_indexed_paths(
        self, parts: list[str], field_path: str, max_indices: int, current_indices: list[int] | None = None
    ) -> list[str]:
        """
        Generate all indexed paths for array field filtering based on nesting depth.
        """
        if current_indices is None:
            return self._generate_indexed_paths(parts, field_path, max_indices, [])

        remaining_depth = field_path.count("[]") - len(current_indices)

        if remaining_depth == 0:
            return [self._build_indexed_path(parts, current_indices)]

        paths = []
        for i in range(max_indices):
            new_indices = [*current_indices, i]
            paths.extend(self._generate_indexed_paths(parts, field_path, max_indices, new_indices))

        return paths

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

    def _apply_was_impersonated_filter(
        self, queryset: QuerySet[ActivityLog], filters: dict[str, Any]
    ) -> QuerySet[ActivityLog]:
        if "was_impersonated" in filters:
            queryset = queryset.filter(was_impersonated=filters["was_impersonated"])
        return queryset

    def _apply_is_system_filter(
        self, queryset: QuerySet[ActivityLog], filters: dict[str, Any]
    ) -> QuerySet[ActivityLog]:
        if "is_system" in filters:
            queryset = queryset.filter(is_system=filters["is_system"])
        return queryset

    def _apply_item_ids_filter(self, queryset: QuerySet[ActivityLog], filters: dict[str, Any]) -> QuerySet[ActivityLog]:
        if filters.get("item_ids"):
            queryset = queryset.filter(item_id__in=filters["item_ids"])
        return queryset

    def _get_type_variants(self, value: Any) -> list[Any]:
        """
        Convert a value to its possible type variants for type-insensitive matching.
        Returns a list of values to try in database queries.
        """
        variants = [value]  # Always include the original value

        # If value is a string, try to convert to other types
        if isinstance(value, str) and value.strip():
            stripped_value = value.strip()

            # Try integer conversion
            try:
                int_val = int(stripped_value)
                if str(int_val) == stripped_value:  # Avoid float-to-int conversion artifacts
                    variants.append(int_val)
            except ValueError:
                pass

            # Try float conversion (only if not already an integer)
            try:
                float_val = float(stripped_value)
                if str(float_val) == stripped_value or (
                    stripped_value.endswith(".0") and str(float_val) == stripped_value[:-2]
                ):
                    variants.append(float_val)
            except ValueError:
                pass

            # Try boolean conversion
            lower_val = stripped_value.lower()
            if lower_val in ("true", "1"):
                variants.append(True)
            elif lower_val in ("false", "0"):
                variants.append(False)

        # If value is boolean, add string and numeric representations
        elif isinstance(value, bool):
            variants.extend([str(value).lower(), str(value), "1" if value else "0"])
        # If value is numeric, add string representation
        elif isinstance(value, int | float):
            variants.append(str(value))

        # Remove duplicates while preserving order
        seen = set()
        unique_variants = []
        for variant in variants:
            # Use a tuple representation for hashable comparison
            key = (type(variant).__name__, variant)
            if key not in seen:
                seen.add(key)
                unique_variants.append(variant)

        return unique_variants

    def _expand_values_with_type_variants(self, value: Any) -> list[Any]:
        """
        Expand a single value or list of values to include all type variants.
        Handles deduplication automatically.
        """
        if not isinstance(value, list | tuple):
            value = [value]

        expanded_values = []
        for v in value:
            expanded_values.extend(self._get_type_variants(v))

        # Remove duplicates while preserving order
        seen = set()
        unique_values = []
        for val in expanded_values:
            key = (type(val).__name__, val)
            if key not in seen:
                seen.add(key)
                unique_values.append(val)

        return unique_values

    def _create_type_insensitive_query(self, field_path: str, operation: str, value: Any) -> Q:
        """
        Create a type-insensitive query condition for the given field path and operation.
        """
        if operation == "exact":
            # Create OR conditions for all type variants
            type_variants = self._get_type_variants(value)
            conditions = [Q(**{field_path: variant}) for variant in type_variants]
            combined_condition = conditions[0]
            for condition in conditions[1:]:
                combined_condition |= condition
            return combined_condition
        elif operation == "in":
            unique_values = self._expand_values_with_type_variants(value)
            return Q(**{f"{field_path}__in": unique_values})
        elif operation == "contains":
            return Q(**{f"{field_path}__icontains": value})
        else:
            return Q(**{field_path: value})
