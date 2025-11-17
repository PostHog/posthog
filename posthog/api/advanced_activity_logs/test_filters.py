from posthog.test.base import BaseTest

from posthog.models.activity_logging.activity_log import ActivityLog

from .filters import AdvancedActivityLogFilterManager


class TestAdvancedActivityLogFilterManager(BaseTest):
    def setUp(self):
        super().setUp()
        self.filter_manager = AdvancedActivityLogFilterManager()

    def test_get_type_variants_string_to_numeric(self):
        variants = self.filter_manager._get_type_variants("42")
        self.assertIn("42", variants)
        self.assertIn(42, variants)

        variants = self.filter_manager._get_type_variants("3.14")
        self.assertIn("3.14", variants)
        self.assertIn(3.14, variants)

        variants = self.filter_manager._get_type_variants("42.0")
        self.assertIn("42.0", variants)
        self.assertIn(42.0, variants)

    def test_get_type_variants_numeric_to_string(self):
        variants = self.filter_manager._get_type_variants(42)
        self.assertIn(42, variants)
        self.assertIn("42", variants)

        variants = self.filter_manager._get_type_variants(3.14)
        self.assertIn(3.14, variants)
        self.assertIn("3.14", variants)

    def test_get_type_variants_boolean_conversion(self):
        variants = self.filter_manager._get_type_variants("true")
        self.assertIn("true", variants)
        self.assertIn(True, variants)

        variants = self.filter_manager._get_type_variants("false")
        self.assertIn("false", variants)
        self.assertIn(False, variants)

        variants = self.filter_manager._get_type_variants("1")
        self.assertIn("1", variants)
        self.assertIn(1, variants)
        self.assertIn(True, variants)

        variants = self.filter_manager._get_type_variants("0")
        self.assertIn("0", variants)
        self.assertIn(0, variants)
        self.assertIn(False, variants)

        variants = self.filter_manager._get_type_variants(True)
        self.assertIn(True, variants)
        self.assertIn("true", variants)
        self.assertIn("True", variants)
        self.assertIn("1", variants)

        variants = self.filter_manager._get_type_variants(False)
        self.assertIn(False, variants)
        self.assertIn("false", variants)
        self.assertIn("False", variants)
        self.assertIn("0", variants)

    def test_get_type_variants_edge_cases(self):
        variants = self.filter_manager._get_type_variants("hello")
        self.assertEqual(variants, ["hello"])

        variants = self.filter_manager._get_type_variants("")
        self.assertEqual(variants, [""])

        variants = self.filter_manager._get_type_variants("   ")
        self.assertEqual(variants, ["   "])

        variants = self.filter_manager._get_type_variants("abc123")
        self.assertEqual(variants, ["abc123"])

    def test_get_type_variants_no_duplicates(self):
        variants = self.filter_manager._get_type_variants("1")
        strings = [v for v in variants if isinstance(v, str)]
        integers = [v for v in variants if isinstance(v, int) and not isinstance(v, bool)]
        booleans = [v for v in variants if isinstance(v, bool)]

        self.assertEqual(len([v for v in strings if v == "1"]), 1)
        self.assertEqual(len([v for v in integers if v == 1]), 1)
        self.assertEqual(len([v for v in booleans if v is True]), 1)

    def _create_activity_log(self, detail: dict) -> ActivityLog:
        return ActivityLog.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            scope="TestScope",
            activity="updated",
            item_id="test-item",
            detail=detail,
        )

    def test_apply_detail_filters_exact_type_insensitive(self):
        log1 = self._create_activity_log({"count": 42})
        log2 = self._create_activity_log({"count": "42"})
        log3 = self._create_activity_log({"count": 42.0})
        log4 = self._create_activity_log({"count": "other"})

        queryset = ActivityLog.objects.filter(id__in=[log1.id, log2.id, log3.id, log4.id])

        filtered = self.filter_manager._apply_detail_filters(queryset, {"count": {"operation": "exact", "value": "42"}})
        result_ids = set(filtered.values_list("id", flat=True))
        expected_ids = {log1.id, log2.id, log3.id}
        self.assertEqual(result_ids, expected_ids)

        filtered = self.filter_manager._apply_detail_filters(queryset, {"count": {"operation": "exact", "value": 42}})
        result_ids = set(filtered.values_list("id", flat=True))
        expected_ids = {log1.id, log2.id, log3.id}
        self.assertEqual(result_ids, expected_ids)

    def test_apply_detail_filters_in_type_insensitive(self):
        log1 = self._create_activity_log({"count": "42"})
        log2 = self._create_activity_log({"count": 42})
        log3 = self._create_activity_log({"count": "other"})

        queryset = ActivityLog.objects.filter(id__in=[log1.id, log2.id, log3.id])

        filtered = self.filter_manager._apply_detail_filters(queryset, {"count": {"operation": "in", "value": ["42"]}})
        result_ids = set(filtered.values_list("id", flat=True))
        expected_ids = {log1.id, log2.id}

        self.assertEqual(result_ids, expected_ids)

    def test_apply_detail_filters_contains_unchanged(self):
        log1 = self._create_activity_log({"message": "Error code 404"})
        log2 = self._create_activity_log({"message": "Success"})

        queryset = ActivityLog.objects.filter(id__in=[log1.id, log2.id])

        filtered = self.filter_manager._apply_detail_filters(
            queryset, {"message": {"operation": "contains", "value": "Error"}}
        )
        result_ids = set(filtered.values_list("id", flat=True))
        self.assertEqual(result_ids, {log1.id})

    def test_nested_object_type_conversion(self):
        log1 = self._create_activity_log({"config": {"timeout": 30}})
        log2 = self._create_activity_log({"config": {"timeout": "30"}})
        log3 = self._create_activity_log({"config": {"timeout": 60}})

        queryset = ActivityLog.objects.filter(id__in=[log1.id, log2.id, log3.id])

        filtered = self.filter_manager._apply_detail_filters(
            queryset, {"config.timeout": {"operation": "exact", "value": "30"}}
        )
        result_ids = set(filtered.values_list("id", flat=True))
        expected_ids = {log1.id, log2.id}
        self.assertEqual(result_ids, expected_ids)

    def test_array_field_type_conversion(self):
        log1 = self._create_activity_log({"items": [{"id": 1}, {"id": 2}]})
        log2 = self._create_activity_log({"items": [{"id": "1"}, {"id": "3"}]})
        log3 = self._create_activity_log({"items": [{"id": "other"}]})

        queryset = ActivityLog.objects.filter(id__in=[log1.id, log2.id, log3.id])

        filtered = self.filter_manager._apply_array_field_filter(queryset, "items[].id", "exact", "1")
        result_ids = set(filtered.values_list("id", flat=True))
        expected_ids = {log1.id, log2.id}
        self.assertEqual(result_ids, expected_ids)

    def test_array_field_in_operation_type_conversion(self):
        log1 = self._create_activity_log({"tags": [{"priority": 1}, {"priority": 3}]})
        log2 = self._create_activity_log({"tags": [{"priority": "2"}, {"priority": "1"}]})
        log3 = self._create_activity_log({"tags": [{"priority": "high"}]})

        queryset = ActivityLog.objects.filter(id__in=[log1.id, log2.id, log3.id])

        filtered = self.filter_manager._apply_array_field_filter(queryset, "tags[].priority", "in", ["1", "2"])
        result_ids = set(filtered.values_list("id", flat=True))
        expected_ids = {log1.id, log2.id}
        self.assertEqual(result_ids, expected_ids)

    def test_deeply_nested_array_fields(self):
        log1 = self._create_activity_log(
            {
                "changes": [
                    {"after": [{"field": {"subarray": [{"value": 42}]}}]},
                    {"after": [{"field": {"subarray": [{"value": "other"}]}}]},
                ]
            }
        )
        log2 = self._create_activity_log({"changes": [{"after": [{"field": {"subarray": [{"value": "42"}]}}]}]})
        log3 = self._create_activity_log({"changes": [{"after": [{"field": {"subarray": [{"value": "different"}]}}]}]})

        queryset = ActivityLog.objects.filter(id__in=[log1.id, log2.id, log3.id])

        filtered = self.filter_manager._apply_array_field_filter(
            queryset, "changes[].after[].field.subarray[].value", "exact", "42"
        )
        result_ids = set(filtered.values_list("id", flat=True))
        expected_ids = {log1.id, log2.id}
        self.assertEqual(result_ids, expected_ids)


class TestTypeConversionIntegration(BaseTest):
    def setUp(self):
        super().setUp()
        self.filter_manager = AdvancedActivityLogFilterManager()

    def test_full_filter_pipeline_with_type_conversion(self):
        log1 = ActivityLog.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            scope="Dashboard",
            activity="updated",
            item_id="123",
            detail={"version": 2, "active": True, "name": "Test Dashboard"},
        )

        log2 = ActivityLog.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            scope="Dashboard",
            activity="created",
            item_id="456",
            detail={"version": "2", "active": "true", "name": "Another Dashboard"},
        )

        filters = {
            "scopes": ["Dashboard"],
            "detail_filters": {
                "version": {"operation": "exact", "value": "2"},
                "active": {"operation": "exact", "value": "true"},
            },
        }

        queryset = ActivityLog.objects.filter(id__in=[log1.id, log2.id])
        filtered = self.filter_manager.apply_filters(queryset, filters)

        result_ids = set(filtered.values_list("id", flat=True))
        expected_ids = {log1.id, log2.id}
        self.assertEqual(result_ids, expected_ids)
