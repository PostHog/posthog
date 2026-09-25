from typing import Any

from posthog.test.base import BaseTest

from posthog.api.advanced_activity_logs.fields_cache import _get_cache_key, get_client
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.user import User

from .field_discovery import AdvancedActivityLogFieldDiscovery


class FieldDiscoveryTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.discovery = AdvancedActivityLogFieldDiscovery(self.organization.id)

    def _create_activity_log(self, scope: str, detail: dict[str, Any]) -> ActivityLog:
        return ActivityLog.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            scope=scope,
            activity="updated",
            item_id="test-item",
            detail=detail,
        )

    def _run_field_discovery(self) -> dict[str, Any]:
        base_queryset = ActivityLog.objects.filter(organization_id=self.organization.id)
        return self.discovery.get_available_filters(base_queryset)

    def _assert_field_discovered(self, results: dict[str, Any], scope: str, field_path: str, expected_types: list[str]):
        detail_fields = results.get("detail_fields", {})
        scope_fields = detail_fields.get(scope, {}).get("fields", [])
        matching_fields = [f for f in scope_fields if f["name"] == field_path]

        self.assertTrue(
            matching_fields,
            f"Field '{field_path}' not found in scope '{scope}'. Available fields: {[f['name'] for f in scope_fields]}",
        )

        field = matching_fields[0]
        self.assertEqual(
            set(field["types"]),
            set(expected_types),
            f"Field '{field_path}' has types {field['types']}, expected {expected_types}",
        )

    def _generate_test_data_from_pattern(self, pattern: str, value: Any = None) -> dict[str, Any]:
        if value is None:
            value = "test_value"

        def create_nested_structure(parts: list[str], val: Any) -> dict[str, Any]:
            if not parts:
                return val

            current_part = parts[0]
            remaining_parts = parts[1:]

            if current_part.endswith("[]"):
                field_name = current_part[:-2]
                if remaining_parts:
                    return {field_name: [create_nested_structure(remaining_parts, val)]}
                else:
                    if isinstance(val, str):
                        return {field_name: [val, f"{val}_2"]}
                    elif isinstance(val, int | float):
                        return {field_name: [val, val + 1]}
                    else:
                        return {field_name: [val, val]}
            else:
                return {current_part: create_nested_structure(remaining_parts, val)}

        parts = pattern.split(".")
        return create_nested_structure(parts, value)

    def test_supported_patterns(self):
        """
        Test field discovery patterns using notation like "settings.theme", "tags[]", "groups[].name".

        Format: (field_pattern, expected_types, test_value)
        - field_pattern: Pattern notation describing the field structure
        - expected_types: List of expected JSON types (["string"], ["number"], etc.)
        - test_value: Sample value to use when generating test data
        """
        supported_patterns = [
            ("field", ["string"], "test_value"),
            ("obj", ["array"], []),
            ("obj[]", ["object"], {}),
            ("arr[].field", ["string"], "array_field_value"),
            ("obj[].field", ["string"], "obj_field"),
            ("obj[].arr[]", ["string"], "nested_array_item"),
            ("obj.obj.field", ["string"], "nested_obj_field"),
            ("obj.arr[]", ["string"], "obj_array_item"),
            ("obj[].subobj.field", ["string"], "deep_obj_field"),
            ("obj[].subobj.arr[].subarr[].field", ["string"], "very_deep_field"),
            ("obj[].subobj.arr[].subarr[].nested_obj.field", ["string"], "ultra_deep_field"),
        ]

        for field_pattern, expected_types, test_value in supported_patterns:
            with self.subTest(pattern=field_pattern):
                ActivityLog.objects.filter(organization_id=self.organization.id).delete()
                try:
                    client = get_client()
                    cache_key = _get_cache_key(str(self.organization.id))
                    client.delete(cache_key)
                except Exception:
                    pass

                detail = self._generate_test_data_from_pattern(field_pattern, test_value)
                self._create_activity_log("Dashboard", detail)
                results = self._run_field_discovery()
                self._assert_field_discovered(results, "Dashboard", field_pattern, expected_types)

    def test_static_filters_dedupe_in_sql_under_the_viewset_ordering(self):
        other_user = User.objects.create_and_join(self.organization, "other@example.com", None)
        ActivityLog.objects.filter(organization_id=self.organization.id).delete()

        for user in (self.user, other_user):
            for scope in ("Dashboard", "Insight"):
                ActivityLog.objects.create(
                    organization_id=self.organization.id,
                    team_id=self.team.id,
                    user=user,
                    scope=scope,
                    activity="updated",
                    item_id="test-item",
                    detail={},
                    client="posthog-web",
                )
        ActivityLog.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=None,
            scope="Dashboard",
            activity="deleted",
            item_id="test-item",
            detail={},
        )

        queryset = (
            ActivityLog.objects.filter(organization_id=self.organization.id)
            .select_related("user")
            .order_by("-created_at", "-id")
        )
        filters = self.discovery._get_static_filters(queryset)

        # One entry per distinct value, not one per activity log row
        self.assertEqual([entry["value"] for entry in filters["scopes"]], ["Dashboard", "Insight"])
        self.assertEqual([entry["value"] for entry in filters["activities"]], ["deleted", "updated"])
        self.assertEqual([entry["value"] for entry in filters["clients"]], ["posthog-web"])
        self.assertEqual(
            sorted(entry["value"] for entry in filters["users"]),
            sorted([str(self.user.uuid), str(other_user.uuid)]),
        )
