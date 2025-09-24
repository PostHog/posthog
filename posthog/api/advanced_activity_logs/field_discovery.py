import threading
import dataclasses
from typing import Any, TypedDict

from django.db import connection
from django.db.models import QuerySet

from posthog.models.activity_logging.activity_log import ActivityLog, Change
from posthog.models.utils import UUIDT

from .fields_cache import cache_fields, get_cached_fields
from .queries import SMALL_ORG_THRESHOLD, QueryBuilder


class ScopeFields(TypedDict):
    fields: list[dict[str, Any]]


DetailFieldsResult = dict[str, ScopeFields]
_analysis_locks = {}


class AdvancedActivityLogFieldDiscovery:
    def __init__(self, organization_id: UUIDT):
        self.organization_id = organization_id

    def get_available_filters(self, base_queryset: QuerySet) -> dict[str, Any]:
        cached = get_cached_fields(str(self.organization_id))
        if cached:
            return cached

        static_filters = self._get_static_filters(base_queryset)
        detail_fields = self._analyze_detail_fields()

        result = {
            "static_filters": static_filters,
            "detail_fields": detail_fields,
        }

        record_count = self._get_org_record_count()
        cache_fields(str(self.organization_id), result, record_count)

        return result

    def _get_static_filters(self, queryset: QuerySet) -> dict[str, list[dict[str, str]]]:
        return {
            "users": self._get_available_users(queryset),
            "scopes": self._get_available_scopes(queryset),
            "activities": self._get_available_activities(queryset),
            "was_impersonated": self._get_available_was_impersonated(queryset),
            "is_system": self._get_available_is_system(queryset),
        }

    def _get_available_users(self, queryset: QuerySet) -> list[dict[str, str]]:
        users_query = queryset.values("user__uuid", "user__first_name", "user__last_name", "user__email").distinct()
        seen_users = set()
        unique_users = []

        for user in users_query:
            if user["user__uuid"] and user["user__uuid"] not in seen_users:
                seen_users.add(user["user__uuid"])
                unique_users.append(
                    {
                        "value": str(user["user__uuid"]),
                        "label": f"{user['user__first_name']} {user['user__last_name']}".strip() or user["user__email"],
                    }
                )

        return unique_users

    def _get_available_scopes(self, queryset: QuerySet) -> list[dict[str, str]]:
        scopes_query = queryset.values_list("scope", flat=True)
        scopes = set(scopes_query)
        return [{"value": scope} for scope in sorted(scopes) if scope]

    def _get_available_activities(self, queryset: QuerySet) -> list[dict[str, str]]:
        activities_query = queryset.values_list("activity", flat=True)
        activities = set(activities_query)
        return [{"value": activity} for activity in sorted(activities) if activity]

    def _analyze_detail_fields(self) -> DetailFieldsResult:
        org_id = str(self.organization_id)

        if org_id not in _analysis_locks:
            _analysis_locks[org_id] = threading.Lock()

        lock = _analysis_locks[org_id]
        with lock:
            result: DetailFieldsResult = {}

            top_level_fields = self._get_top_level_fields()
            self._merge_fields_into_result(result, top_level_fields)

            nested_fields = self._compute_nested_fields_realtime()
            self._merge_fields_into_result(result, nested_fields)

            changes_fields = self._get_changes_fields()
            self._merge_fields_into_result(result, changes_fields)

        _analysis_locks.pop(org_id, None)

        return result

    def _get_org_record_count(self) -> int:
        return ActivityLog.objects.filter(organization_id=self.organization_id).count()

    def _compute_nested_fields_realtime(self) -> list[tuple[str, str, list[str]]]:
        org_record_count = self._get_org_record_count()

        if org_record_count <= SMALL_ORG_THRESHOLD:
            results = self._compute_fields_full_traversal()
        else:
            results = self._compute_fields_with_batching_and_sampling()

        return results

    def _compute_fields_full_traversal(self) -> list[tuple[str, str, list[str]]]:
        results = []

        query_tuples = QueryBuilder.build_queries(str(self.organization_id), type="full")
        queries = [query for query, _ in query_tuples]

        with connection.cursor() as cursor:
            for query in queries:
                cursor.execute(query, [str(self.organization_id)])
                query_results = cursor.fetchall()
                results.extend([(scope, field_name, field_types) for scope, field_name, field_types in query_results])

        return self._deduplicate_results(results)

    def _compute_fields_with_batching_and_sampling(self) -> list[tuple[str, str, list[str]]]:
        results = []

        query_tuples = QueryBuilder.build_queries(str(self.organization_id), type="batched_sampling")
        queries = [query for query, _ in query_tuples]

        with connection.cursor() as cursor:
            for query in queries:
                cursor.execute(query, [str(self.organization_id)])
                query_results = cursor.fetchall()
                results.extend([(scope, field_name, field_types) for scope, field_name, field_types in query_results])

        return self._deduplicate_results(results)

    def _deduplicate_results(self, all_results: list[tuple[str, str, list[str]]]) -> list[tuple[str, str, list[str]]]:
        field_map: dict[tuple[str, str], list[str]] = {}
        for scope, field_path, field_types in all_results:
            key = (scope, field_path)
            if key in field_map:
                existing_types = set(field_map[key])
                new_types = set(field_types)
                field_map[key] = list(existing_types.union(new_types))
            else:
                field_map[key] = field_types

        return [(scope, field_path, field_types) for (scope, field_path), field_types in field_map.items()]

    def _get_top_level_fields(self) -> list[tuple[str, str, list[str]]]:
        query, params = QueryBuilder.build_top_level_fields_query(str(self.organization_id))

        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return [(scope, field_name, field_types) for scope, field_name, field_types in cursor.fetchall()]

    def _merge_fields_into_result(self, result: DetailFieldsResult, fields: list[tuple[str, str, list[str]]]) -> None:
        for scope, field_name, field_types in fields:
            if scope not in result:
                result[scope] = {"fields": []}

            existing_field = None
            for existing in result[scope]["fields"]:
                if existing["name"] == field_name:
                    existing_field = existing
                    break

            if existing_field:
                existing_types = set(existing_field["types"])
                new_types = set(field_types)
                existing_field["types"] = list(existing_types.union(new_types))
            else:
                result[scope]["fields"].append({"name": field_name, "types": field_types})

    def _get_changes_fields(self) -> list[tuple[str, str, list[str]]]:
        result = []
        for field in dataclasses.fields(Change):
            field_name = f"changes[].{field.name}"
            if field.name == "type":
                field_types = ["string"]
            elif field.name == "action":
                field_types = ["string"]
            elif field.name == "field":
                field_types = ["string"]
            else:
                field_types = ["any"]
            result.append(("General", field_name, field_types))
        return result

    def _get_available_was_impersonated(self, queryset: QuerySet) -> list[dict[str, str]]:
        was_impersonated_values = queryset.values_list("was_impersonated", flat=True).distinct()
        return [{"value": str(value).lower(), "label": "Yes" if value else "No"} for value in was_impersonated_values]

    def _get_available_is_system(self, queryset: QuerySet) -> list[dict[str, str]]:
        is_system_values = queryset.values_list("is_system", flat=True).distinct()
        return [{"value": str(value).lower(), "label": "Yes" if value else "No"} for value in is_system_values]
