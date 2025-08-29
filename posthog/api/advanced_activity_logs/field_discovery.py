import dataclasses
from typing import Any, TypedDict

from django.db import connection
from django.db.models import QuerySet

from posthog.models.activity_logging.activity_log import Change
from posthog.models.utils import UUIDT

from .queries import QueryBuilder


class ScopeFields(TypedDict):
    fields: list[dict[str, Any]]


DetailFieldsResult = dict[str, ScopeFields]


class AdvancedActivityLogFieldDiscovery:
    """
    Handles discovery and analysis of filterable fields in advanced activity log details.

    This class analyzes the JSON structure of activity log detail fields to discover
    what fields are available for filtering across different scopes.
    """

    def __init__(self, organization_id: UUIDT):
        self.organization_id = organization_id
        self.query_builder = QueryBuilder()

    def get_available_filters(self, base_queryset: QuerySet) -> dict[str, Any]:
        static_filters = self._get_static_filters(base_queryset)
        detail_fields = self._analyze_detail_fields()

        return {
            "static_filters": static_filters,
            "detail_fields": detail_fields,
        }

    def _get_static_filters(self, queryset: QuerySet) -> dict[str, list[dict[str, str]]]:
        """Get static filter options for users, scopes, and activities."""
        return {
            "users": self._get_available_users(queryset),
            "scopes": self._get_available_scopes(queryset),
            "activities": self._get_available_activities(queryset),
        }

    def _get_available_users(self, queryset: QuerySet) -> list[dict[str, str]]:
        users_query = queryset.values("user__id", "user__first_name", "user__last_name", "user__email").distinct()
        seen_users = set()
        unique_users = []

        for user in users_query:
            if user["user__id"] and user["user__id"] not in seen_users:
                seen_users.add(user["user__id"])
                unique_users.append(
                    {
                        "value": str(user["user__id"]),
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
        result: DetailFieldsResult = {}

        top_level_fields = self._get_top_level_fields()
        self._merge_fields_into_result(result, top_level_fields)

        nested_fields = self._get_nested_fields()
        self._merge_fields_into_result(result, nested_fields)

        changes_fields = self._get_changes_fields()
        self._merge_fields_into_result(result, changes_fields)

        return result

    def _get_nested_fields(self) -> list[tuple[str, str, list[str]]]:
        """Discover nested fields like context.level, trigger.job_type."""
        query, params = self.query_builder.build_nested_fields_query(str(self.organization_id))

        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return [(scope, field_name, field_types) for scope, field_name, field_types in cursor.fetchall()]

    def _get_top_level_fields(self) -> list[tuple[str, str, list[str]]]:
        """Discover top-level fields like name, label."""
        query, params = self.query_builder.build_top_level_fields_query(str(self.organization_id))

        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return [(scope, field_name, field_types) for scope, field_name, field_types in cursor.fetchall()]

    def _merge_fields_into_result(self, result: DetailFieldsResult, fields: list[tuple[str, str, list[str]]]) -> None:
        for scope, field_name, field_types in fields:
            if scope not in result:
                result[scope] = {"fields": []}

            result[scope]["fields"].append({"name": field_name, "types": field_types})

    def _get_changes_fields(self) -> list[tuple[str, str, list[str]]]:
        result = []
        for field in dataclasses.fields(Change):
            field_name = f"changes.{field.name}"
            result.append(("ActivityLog", field_name, ["string"]))  # TODO: dynamically generate types
        return result
