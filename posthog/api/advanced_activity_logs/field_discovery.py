import gc
import json
import dataclasses
from datetime import timedelta
from typing import Any, TypedDict

from django.db import connection
from django.db.models import Q, QuerySet
from django.utils import timezone

from posthog.models.activity_logging.activity_log import ActivityLog, Change
from posthog.models.utils import UUIDT

from .constants import BATCH_SIZE, SAMPLING_PERCENTAGE, SMALL_ORG_THRESHOLD
from .fields_cache import cache_fields, get_cached_fields


class ScopeFields(TypedDict):
    fields: list[dict[str, Any]]


DetailFieldsResult = dict[str, ScopeFields]


class AdvancedActivityLogFieldDiscovery:
    """Derives the filter options an activity log caller may choose from.

    `team_id` narrows every query and the cache key to a single project. It stays `None` for the
    organization-wide callers (the org-scoped endpoint and the background cache task), which are
    allowed to see across projects. `include_org_scoped` widens a project's scope to the
    organization-scoped rows that project's feed also shows, matching
    `apply_organization_scoped_filter`. `user_id` identifies the caller a cached entry belongs to,
    and stays `None` for the background task, which computes with no caller.
    """

    def __init__(
        self,
        organization_id: UUIDT,
        team_id: int | None = None,
        include_org_scoped: bool = False,
        user_id: int | None = None,
    ):
        self.organization_id = organization_id
        self.team_id = team_id
        self.include_org_scoped = include_org_scoped
        self.user_id = user_id

    def get_available_filters(self, base_queryset: QuerySet) -> dict[str, Any]:
        # The filter options themselves come from the caller's authorized queryset below, so they can
        # never name a project, scope, or actor whose rows that caller cannot read. This count only
        # chooses between the cached and the live branch, so it stays on the plain scoped count:
        # counting the authorized queryset instead would evaluate the visibility, loop and canvas
        # exclusions (JSON predicates on `detail`) over every row, on the organization-wide request
        # this branch exists to keep cheap.
        record_count = self._get_record_count()

        if record_count > SMALL_ORG_THRESHOLD:
            cached = get_cached_fields(str(self.organization_id), self.team_id, self.user_id)
            if cached is None and self.team_id is None:
                # The background task computes one organization-wide entry with no caller attached.
                # Only an organization-wide caller may read it, and that route is admin-gated.
                cached = get_cached_fields(str(self.organization_id))
            if cached:
                return cached
            return {
                "static_filters": {"users": [], "scopes": [], "activities": [], "clients": []},
                "detail_fields": {},
            }

        static_filters = self._get_static_filters(base_queryset)
        detail_fields = self._analyze_detail_fields_memory(base_queryset)

        result = {
            "static_filters": static_filters,
            "detail_fields": detail_fields,
        }

        cache_fields(str(self.organization_id), result, record_count, self.team_id, self.user_id)
        return result

    def _get_static_filters(self, queryset: QuerySet) -> dict[str, list[dict[str, str]]]:
        return {
            "users": self._get_available_users(queryset),
            "scopes": self._get_available_scopes(queryset),
            "activities": self._get_available_activities(queryset),
            "clients": self._get_available_clients(queryset),
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

    def _get_available_clients(self, queryset: QuerySet) -> list[dict[str, str]]:
        clients_query = queryset.values_list("client", flat=True)
        clients = set(clients_query)
        return [{"value": client} for client in sorted(c for c in clients if c)]

    def _analyze_detail_fields_memory(self, base_queryset: QuerySet) -> DetailFieldsResult:
        fields = self._discover_fields_memory(base_queryset, batch_size=BATCH_SIZE)
        converted_fields = self._convert_to_discovery_format(fields)

        result: DetailFieldsResult = {}
        self._merge_fields_into_result(result, converted_fields)

        changes_fields = self._get_changes_fields()
        self._merge_fields_into_result(result, changes_fields)

        return result

    def _get_record_count(self) -> int:
        return self._get_base_queryset().count()

    def get_activity_logs_queryset(self, hours_back: int | None = None) -> QuerySet:
        """Get the base queryset for activity logs, optionally filtered by time."""
        queryset = self._get_base_queryset().filter(detail__isnull=False)

        if hours_back is not None:
            cutoff_time = timezone.now() - timedelta(hours=hours_back)
            queryset = queryset.filter(created_at__gte=cutoff_time)

        return queryset

    def get_sampled_records(self, limit: int, offset: int = 0) -> list[dict]:
        """Get sampled records using SQL TABLESAMPLE for large datasets."""
        params: list[Any] = [str(self.organization_id)]
        team_clause = ""
        if self.team_id is not None:
            # Mirrors `_get_base_queryset`, so sampling covers the same rows the count sizes.
            team_clause = "AND (team_id = %s OR team_id IS NULL)" if self.include_org_scoped else "AND team_id = %s"
            params.append(self.team_id)
        params.extend([limit, offset])

        query = f"""
            SELECT scope, detail
            FROM posthog_activitylog TABLESAMPLE SYSTEM ({SAMPLING_PERCENTAGE})
            WHERE organization_id = %s
            {team_clause}
            AND detail IS NOT NULL
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """

        with connection.cursor() as cursor:
            cursor.execute(query, params)
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

        existing_cache = get_cached_fields(str(self.organization_id), self.team_id, self.user_id)
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

        record_count = self._get_record_count()
        cache_fields(str(self.organization_id), cache_data, record_count, self.team_id, self.user_id)

    def _get_base_queryset(self) -> QuerySet:
        queryset = ActivityLog.objects.filter(organization_id=self.organization_id)
        if self.team_id is None:
            return queryset
        if self.include_org_scoped:
            return queryset.filter(
                Q(team_id=self.team_id) | Q(team_id__isnull=True, organization_id=self.organization_id)
            )
        return queryset.filter(team_id=self.team_id)

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
        self, base_queryset: QuerySet, batch_size: int = BATCH_SIZE
    ) -> dict[str, set[tuple[str, str]]]:
        all_fields: dict[str, set[tuple[str, str]]] = {}
        # The caller's queryset carries select_related for the list serializer, which values() cannot use.
        detail_queryset = base_queryset.select_related(None).filter(detail__isnull=False)
        total_records = detail_queryset.count()

        if total_records == 0:
            return all_fields

        for offset in range(0, total_records, batch_size):
            batch_fields = self._process_batch_memory(detail_queryset, offset, batch_size)
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
        self, detail_queryset: QuerySet, offset: int, limit: int
    ) -> dict[str, set[tuple[str, str]]]:
        records = [
            {"scope": record["scope"], "detail": record["detail"]}
            for record in detail_queryset.values("scope", "detail")[offset : offset + limit]
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
            "clients": existing.get("clients", []),
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

        # Merge clients
        existing_clients = {c["value"] for c in merged["clients"]}
        for client in new.get("clients", []):
            if client["value"] not in existing_clients:
                merged["clients"].append(client)

        return merged
