import re
from typing import Any

from django.db.models import JSONField, Q, QuerySet
from django.db.models.fields.json import KeyTransform

from rest_framework import serializers

from posthog.models.activity_logging.activity_log import ActivityLog

_ALLOWED_DETAIL_FILTER_OPERATIONS = {"exact", "contains", "in"}

# Names Django resolves as a lookup instead of a JSON key. A field path segment matching one of
# these turns the caller's key into the ORM operation: `regex` becomes `detail::text ~ <value>`
# and `name.regex` becomes `(detail ->> 'name')::text ~ <value>`, which evaluates an arbitrary
# Postgres regular expression against every row. Computed from Django's registries so the set
# stays correct when Django adds lookups.
_DJANGO_LOOKUP_NAMES = frozenset(JSONField().get_lookups()) | frozenset(KeyTransform.get_lookups())

_MAX_DETAIL_FILTERS = 100
_MAX_FIELD_PATH_LENGTH = 500
# Array filters only look at the first _MAX_ARRAY_INDICES_TO_CHECK elements of each array. Each
# `[]` marker in a field path multiplies the number of generated index permutations by that number,
# and every permutation costs a path string plus a Q object, so capping the product keeps a deeply
# nested path from exhausting the worker's memory before any SQL runs. The cap is 5 ** 3, which
# lets a path nest three arrays and rejects a fourth.
_MAX_ARRAY_INDICES_TO_CHECK = 5
_MAX_INDEXED_PATHS = 125


def validate_detail_filters(detail_filters: Any) -> dict[str, Any]:
    """Reject detail filters that Django would turn into an ORM operation or an unbounded expansion.

    Raises ``serializers.ValidationError`` so callers surface a 400 rather than running the query.
    """
    if not isinstance(detail_filters, dict):
        raise serializers.ValidationError("detail_filters must be an object.")

    if len(detail_filters) > _MAX_DETAIL_FILTERS:
        raise serializers.ValidationError(f"detail_filters accepts at most {_MAX_DETAIL_FILTERS} entries.")

    for field_path, filter_config in detail_filters.items():
        _validate_detail_filter(field_path, filter_config)

    return detail_filters


def _validate_detail_filter(field_path: Any, filter_config: Any) -> None:
    if not isinstance(field_path, str) or not field_path:
        raise serializers.ValidationError("Detail filter field paths must be non-empty strings.")

    if len(field_path) > _MAX_FIELD_PATH_LENGTH:
        raise serializers.ValidationError(
            f"Detail filter field paths must be at most {_MAX_FIELD_PATH_LENGTH} characters."
        )

    if not isinstance(filter_config, dict):
        raise serializers.ValidationError(f"Detail filter '{field_path}' must be an object.")

    operation = filter_config.get("operation", "exact")
    if operation not in _ALLOWED_DETAIL_FILTER_OPERATIONS:
        raise serializers.ValidationError(
            f"Unsupported detail filter operation '{operation}'. "
            f"Allowed operations: {', '.join(sorted(_ALLOWED_DETAIL_FILTER_OPERATIONS))}."
        )

    # `__` is Django's lookup separator, so it would let a path traverse relationships or append a
    # lookup regardless of the per-segment checks below.
    if "__" in field_path:
        raise serializers.ValidationError(f"Detail filter field path '{field_path}' contains '__'.")

    if _MAX_ARRAY_INDICES_TO_CHECK ** field_path.count("[]") > _MAX_INDEXED_PATHS:
        raise serializers.ValidationError(f"Detail filter field path '{field_path}' nests too many arrays.")

    stripped = field_path.replace("[]", "")
    for segment in stripped.split("."):
        if not segment:
            raise serializers.ValidationError(f"Detail filter field path '{field_path}' has an empty segment.")

    # Check the components Django will actually see, not the dot-separated segments. A segment
    # ending in `_` next to one starting with `_` joins into a run of underscores that shifts the
    # `__` boundary, so a lookup name can surface as its own component without ever having been a
    # segment -- and reach the database as a lookup.
    for component in stripped.replace(".", "__").split("__"):
        if not component:
            raise serializers.ValidationError(
                f"Detail filter field path '{field_path}' has an ambiguous underscore boundary."
            )
        if component in _DJANGO_LOOKUP_NAMES:
            raise serializers.ValidationError(
                f"Detail filter field path '{field_path}' uses reserved segment '{component}'."
            )


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
        queryset = self._apply_clients_filter(queryset, filters)
        queryset = self._apply_ip_addresses_filter(queryset, filters)
        queryset = self._apply_team_ids_filter(queryset, filters)
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
        if not detail_filters:
            return queryset

        validate_detail_filters(detail_filters)

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
        # nosemgrep: orm-field-injection -- field_path checked by validate_detail_filters (no `__`, no segment named after a Django lookup)
        return queryset.filter(**{f"detail__{base_array_path}__icontains": value})

    def _apply_array_exact_filter(
        self, queryset: QuerySet[ActivityLog], field_path: str, operation: str, value: Any
    ) -> QuerySet[ActivityLog]:
        parts = field_path.split("[].")
        if len(parts) < 2:
            return self._apply_array_contains_filter(queryset, field_path, value)

        query_conditions = []

        indexed_paths = self._generate_indexed_paths(parts, field_path, _MAX_ARRAY_INDICES_TO_CHECK)

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
        was_impersonated = filters.get("was_impersonated")
        if was_impersonated is not None:
            queryset = queryset.filter(was_impersonated=was_impersonated)
        return queryset

    def _apply_is_system_filter(
        self, queryset: QuerySet[ActivityLog], filters: dict[str, Any]
    ) -> QuerySet[ActivityLog]:
        is_system = filters.get("is_system")
        if is_system is not None:
            queryset = queryset.filter(is_system=is_system)
        return queryset

    def _apply_item_ids_filter(self, queryset: QuerySet[ActivityLog], filters: dict[str, Any]) -> QuerySet[ActivityLog]:
        if filters.get("item_ids"):
            queryset = queryset.filter(item_id__in=filters["item_ids"])
        return queryset

    def _apply_clients_filter(self, queryset: QuerySet[ActivityLog], filters: dict[str, Any]) -> QuerySet[ActivityLog]:
        if filters.get("clients"):
            queryset = queryset.filter(client__in=filters["clients"])
        return queryset

    def _apply_ip_addresses_filter(
        self, queryset: QuerySet[ActivityLog], filters: dict[str, Any]
    ) -> QuerySet[ActivityLog]:
        ip_filters = [ip for ip in (filters.get("ip_addresses") or []) if ip]
        if not ip_filters:
            return queryset

        # Always go through __iregex so partial values (e.g. `192.168.1`) match no rows
        # instead of triggering Django's GenericIPAddressField validation on __in lookups.
        exact_values = [v for v in ip_filters if "*" not in v]
        wildcard_values = [v for v in ip_filters if "*" in v]

        q = Q()
        if exact_values:
            q |= Q(ip_address__in=exact_values)
        for value in wildcard_values:
            regex = "^" + "".join(".*" if c == "*" else re.escape(c) for c in value) + "$"
            q |= Q(ip_address__iregex=regex)
        return queryset.filter(q)

    def _apply_team_ids_filter(self, queryset: QuerySet[ActivityLog], filters: dict[str, Any]) -> QuerySet[ActivityLog]:
        if filters.get("team_ids"):
            queryset = queryset.filter(team_id__in=filters["team_ids"])
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
            # nosemgrep: orm-field-injection -- field_path checked by validate_detail_filters (no `__`, no segment named after a Django lookup)
            return Q(**{f"{field_path}__in": unique_values})
        elif operation == "contains":
            # nosemgrep: orm-field-injection -- field_path checked by validate_detail_filters (no `__`, no segment named after a Django lookup)
            return Q(**{f"{field_path}__icontains": value})
        else:
            return Q(**{field_path: value})
