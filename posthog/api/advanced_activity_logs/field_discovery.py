import gc
import json
import dataclasses
from datetime import timedelta
from typing import Any, TypedDict

from django.db import connection
from django.db.models import QuerySet
from django.utils import timezone

from posthog.models.activity_logging.activity_log import ActivityLog, Change
from posthog.models.utils import UUIDT

from .constants import BATCH_SIZE, SAMPLING_PERCENTAGE, SMALL_ORG_THRESHOLD
from .fields_cache import cache_fields, get_cached_fields


class ScopeFields(TypedDict):
    fields: list[dict[str, Any]]


DetailFieldsResult = dict[str, ScopeFields]


class AdvancedActivityLogFieldDiscovery:
    def __init__(self, organization_id: UUIDT):
        self.organization_id = organization_id

    def get_available_filters(self, base_queryset: QuerySet) -> dict[str, Any]:
        record_count = self._get_org_record_count()

        if record_count > SMALL_ORG_THRESHOLD:
            cached = get_cached_fields(str(self.organization_id))
            if cached:
                return cached
            return {
                "static_filters": {"users": [], "scopes": [], "activities": []},
                "detail_fields": {},
            }

        static_filters = self._get_static_filters(base_queryset)
        detail_fields = self._analyze_detail_fields_memory()

        result = {
            "static_filters": static_filters,
            "detail_fields": detail_fields,
        }

        cache_fields(str(self.organization_id), result, record_count)
        return result

    def _get_static_filters(self, queryset: QuerySet) -> dict[str, list[dict[str, str]]]:
        return {
            "users": self._get_available_users(queryset),
            "scopes": self._get_available_scopes(queryset),
            "activities": self._get_available_activities(queryset),
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

    def _analyze_detail_fields_memory(self) -> DetailFieldsResult:
        fields = self._discover_fields_memory(batch_size=BATCH_SIZE, use_sampling=False)
        converted_fields = self._convert_to_discovery_format(fields)

        result: DetailFieldsResult = {}
        self._merge_fields_into_result(result, converted_fields)

        changes_fields = self._get_changes_fields()
        self._merge_fields_into_result(result, changes_fields)

        return result

    def _get_org_record_count(self) -> int:
        return ActivityLog.objects.filter(organization_id=self.organization_id).count()

    def get_activity_logs_queryset(self, hours_back: int | None = None) -> QuerySet:
        """Get the base queryset for activity logs, optionally filtered by time."""
        queryset = ActivityLog.objects.filter(organization_id=self.organization_id, detail__isnull=False)

        if hours_back is not None:
            cutoff_time = timezone.now() - timedelta(hours=hours_back)
            queryset = queryset.filter(created_at__gte=cutoff_time)

        return queryset

    def get_sampled_records(self, limit: int, offset: int = 0) -> list[dict]:
        """Get sampled records using SQL TABLESAMPLE for large datasets."""
        query = f"""
            SELECT scope, detail
            FROM posthog_activitylog TABLESAMPLE SYSTEM ({SAMPLING_PERCENTAGE})
            WHERE organization_id = %s
            AND detail IS NOT NULL
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """

        with connection.cursor() as cursor:
            cursor.execute(query, [str(self.organization_id), limit, offset])
            records = []
            for row in cursor.fetchall():
                scope, detail = row
                if isinstance(detail, str):
                    try:
                        detail = json.loads(detail)
                    except (json.JSONDecodeError, TypeError):
                        detail = None
                records.append({"scope": scope, "detail": detail})
        return records

    def process_batch_for_large_org(self, records: list[dict], hours_back: int | None = None) -> None:
        """Process a batch of records for large organizations.

        Args:
            records: List of activity log records to process
            hours_back: If provided, used to get appropriate static filters for the time range
        """
        # Process the provided records
        batch_fields = self._extract_fields_from_records(records)
        batch_converted = self._convert_to_discovery_format(batch_fields)

        existing_cache = get_cached_fields(str(self.organization_id))
        if existing_cache and "detail_fields" in existing_cache:
            current_detail_fields = existing_cache["detail_fields"]
            self._merge_fields_into_result(current_detail_fields, batch_converted)
        else:
            current_detail_fields = {}
            self._merge_fields_into_result(current_detail_fields, batch_converted)

        # Get static filters for the appropriate time range
        if hours_back is not None:
            recent_queryset = self.get_activity_logs_queryset(hours_back=hours_back)
            new_static_filters = self._get_static_filters(recent_queryset)

            # Merge with existing static filters
            if existing_cache and "static_filters" in existing_cache:
                static_filters = self._merge_static_filters(existing_cache["static_filters"], new_static_filters)
            else:
                static_filters = new_static_filters
        else:
            if existing_cache and existing_cache.get("static_filters"):
                static_filters = existing_cache["static_filters"]
            else:
                static_filters = self._get_static_filters(self._get_base_queryset())

        cache_data = {
            "static_filters": static_filters,
            "detail_fields": current_detail_fields,
        }

        record_count = self._get_org_record_count()
        cache_fields(str(self.organization_id), cache_data, record_count)

    def _get_base_queryset(self):
        return ActivityLog.objects.filter(organization_id=self.organization_id)

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

    def _discover_fields_memory(
        self, batch_size: int = 10000, use_sampling: bool = True
    ) -> dict[str, set[tuple[str, str]]]:
        all_fields: dict[str, set[tuple[str, str]]] = {}
        total_records = self._get_record_count_for_memory()

        if total_records == 0:
            return all_fields

        if use_sampling:
            sampled_records = int(total_records * (SAMPLING_PERCENTAGE / 100))
            records_to_process = sampled_records
        else:
            records_to_process = total_records

        for offset in range(0, records_to_process, batch_size):
            batch_fields = self._process_batch_memory(offset, batch_size, use_sampling)
            self._merge_fields_memory(all_fields, batch_fields)
            del batch_fields
            gc.collect()

        return all_fields

    def _extract_fields_from_records(self, records: list[dict]) -> dict[str, set[tuple[str, str]]]:
        """Extract field information from a list of activity log records."""
        batch_fields: dict[str, set[tuple[str, str]]] = {}

        for record in records:
            scope = record["scope"]
            detail = record["detail"]

            if not isinstance(detail, dict):
                continue

            if scope not in batch_fields:
                batch_fields[scope] = set()

            paths = self._extract_json_paths(detail)
            for path, field_type in paths:
                batch_fields[scope].add((path, field_type))

        return batch_fields

    def _process_batch_memory(
        self, offset: int, limit: int, use_sampling: bool = True
    ) -> dict[str, set[tuple[str, str]]]:
        """Legacy method for backward compatibility."""
        if use_sampling:
            records = self.get_sampled_records(limit, offset)
        else:
            records = [
                {"scope": record["scope"], "detail": record["detail"]}
                for record in self.get_activity_logs_queryset().values("scope", "detail")[offset : offset + limit]
            ]

        return self._extract_fields_from_records(records)

    def _extract_json_paths(self, obj: Any, prefix: str = "") -> set[tuple[str, str]]:
        paths = set()

        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = f"{prefix}.{key}" if prefix else key
                field_type = self._get_field_type(value)
                paths.add((current_path, field_type))

                nested_paths = self._extract_json_paths(value, current_path)
                paths.update(nested_paths)

        elif isinstance(obj, list) and obj:
            array_path = f"{prefix}[]" if prefix else "[]"

            sample_size = min(len(obj), 10)
            sample_items = obj[:sample_size]

            for item in sample_items:
                if item is not None:
                    item_type = self._get_field_type(item)
                    paths.add((array_path, item_type))

                    if isinstance(item, dict | list):
                        nested_paths = self._extract_json_paths(item, array_path)
                        paths.update(nested_paths)

        return paths

    def _get_field_type(self, value: Any) -> str:
        if value is None:
            return "null"
        elif isinstance(value, bool):
            return "boolean"
        elif isinstance(value, int):
            return "number"
        elif isinstance(value, float):
            return "number"
        elif isinstance(value, str):
            return "string"
        elif isinstance(value, list):
            return "array"
        elif isinstance(value, dict):
            return "object"
        else:
            return "unknown"

    def _merge_fields_memory(
        self, all_fields: dict[str, set[tuple[str, str]]], batch_fields: dict[str, set[tuple[str, str]]]
    ) -> None:
        for scope, fields in batch_fields.items():
            if scope not in all_fields:
                all_fields[scope] = set()
            all_fields[scope].update(fields)

    def _get_record_count_for_memory(self) -> int:
        return ActivityLog.objects.filter(organization_id=self.organization_id, detail__isnull=False).count()

    def _convert_to_discovery_format(self, fields: dict[str, set[tuple[str, str]]]) -> list[tuple[str, str, list[str]]]:
        result = []

        for scope, field_set in fields.items():
            path_types: dict[str, set[str]] = {}

            for field_path, field_type in field_set:
                if field_path not in path_types:
                    path_types[field_path] = set()
                path_types[field_path].add(field_type)

            for field_path, types in path_types.items():
                result.append((scope, field_path, sorted(types)))

        return result

    def _merge_static_filters(self, existing: dict, new: dict) -> dict:
        """Merge static filters additively"""
        merged = {
            "users": existing.get("users", []),
            "scopes": existing.get("scopes", []),
            "activities": existing.get("activities", []),
        }

        # Merge users (by uuid)
        existing_user_ids = {u["value"] for u in merged["users"]}
        for user in new.get("users", []):
            if user["value"] not in existing_user_ids:
                merged["users"].append(user)

        # Merge scopes
        existing_scopes = {s["value"] for s in merged["scopes"]}
        for scope in new.get("scopes", []):
            if scope["value"] not in existing_scopes:
                merged["scopes"].append(scope)

        # Merge activities
        existing_activities = {a["value"] for a in merged["activities"]}
        for activity in new.get("activities", []):
            if activity["value"] not in existing_activities:
                merged["activities"].append(activity)

        return merged
