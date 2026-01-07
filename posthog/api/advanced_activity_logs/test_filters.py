from posthog.test.base import BaseTest

from posthog.models.activity_logging.activity_log import ActivityLog

from .filters import AdvancedActivityLogFilterManager


class TestAdvancedActivityLogFilterManager(BaseTest):
    def setUp(self):
        super().setUp()
        self.filter_manager = AdvancedActivityLogFilterManager()

    def test_get_type_variants_string_to_numeric(self):
        variants = self.filter_manager._get_type_variants("42")
        assert "42" in variants
        assert 42 in variants

        variants = self.filter_manager._get_type_variants("3.14")
        assert "3.14" in variants
        assert 3.14 in variants

        variants = self.filter_manager._get_type_variants("42.0")
        assert "42.0" in variants
        assert 42.0 in variants

    def test_get_type_variants_numeric_to_string(self):
        variants = self.filter_manager._get_type_variants(42)
        assert 42 in variants
        assert "42" in variants

        variants = self.filter_manager._get_type_variants(3.14)
        assert 3.14 in variants
        assert "3.14" in variants

    def test_get_type_variants_boolean_conversion(self):
        variants = self.filter_manager._get_type_variants("true")
        assert "true" in variants
        assert True in variants

        variants = self.filter_manager._get_type_variants("false")
        assert "false" in variants
        assert False in variants

        variants = self.filter_manager._get_type_variants("1")
        assert "1" in variants
        assert 1 in variants
        assert True in variants

        variants = self.filter_manager._get_type_variants("0")
        assert "0" in variants
        assert 0 in variants
        assert False in variants

        variants = self.filter_manager._get_type_variants(True)
        assert True in variants
        assert "true" in variants
        assert "True" in variants
        assert "1" in variants

        variants = self.filter_manager._get_type_variants(False)
        assert False in variants
        assert "false" in variants
        assert "False" in variants
        assert "0" in variants

    def test_get_type_variants_edge_cases(self):
        variants = self.filter_manager._get_type_variants("hello")
        assert variants == ["hello"]

        variants = self.filter_manager._get_type_variants("")
        assert variants == [""]

        variants = self.filter_manager._get_type_variants("   ")
        assert variants == ["   "]

        variants = self.filter_manager._get_type_variants("abc123")
        assert variants == ["abc123"]

    def test_get_type_variants_no_duplicates(self):
        variants = self.filter_manager._get_type_variants("1")
        strings = [v for v in variants if isinstance(v, str)]
        integers = [v for v in variants if isinstance(v, int) and not isinstance(v, bool)]
        booleans = [v for v in variants if isinstance(v, bool)]

        assert len([v for v in strings if v == "1"]) == 1
        assert len([v for v in integers if v == 1]) == 1
        assert len([v for v in booleans if v is True]) == 1

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
        assert result_ids == expected_ids

        filtered = self.filter_manager._apply_detail_filters(queryset, {"count": {"operation": "exact", "value": 42}})
        result_ids = set(filtered.values_list("id", flat=True))
        expected_ids = {log1.id, log2.id, log3.id}
        assert result_ids == expected_ids

    def test_apply_detail_filters_in_type_insensitive(self):
        log1 = self._create_activity_log({"count": "42"})
        log2 = self._create_activity_log({"count": 42})
        log3 = self._create_activity_log({"count": "other"})

        queryset = ActivityLog.objects.filter(id__in=[log1.id, log2.id, log3.id])

        filtered = self.filter_manager._apply_detail_filters(queryset, {"count": {"operation": "in", "value": ["42"]}})
        result_ids = set(filtered.values_list("id", flat=True))
        expected_ids = {log1.id, log2.id}

        assert result_ids == expected_ids

    def test_apply_detail_filters_contains_unchanged(self):
        log1 = self._create_activity_log({"message": "Error code 404"})
        log2 = self._create_activity_log({"message": "Success"})

        queryset = ActivityLog.objects.filter(id__in=[log1.id, log2.id])

        filtered = self.filter_manager._apply_detail_filters(
            queryset, {"message": {"operation": "contains", "value": "Error"}}
        )
        result_ids = set(filtered.values_list("id", flat=True))
        assert result_ids == {log1.id}

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
        assert result_ids == expected_ids

    def test_array_field_type_conversion(self):
        log1 = self._create_activity_log({"items": [{"id": 1}, {"id": 2}]})
        log2 = self._create_activity_log({"items": [{"id": "1"}, {"id": "3"}]})
        log3 = self._create_activity_log({"items": [{"id": "other"}]})

        queryset = ActivityLog.objects.filter(id__in=[log1.id, log2.id, log3.id])

        filtered = self.filter_manager._apply_array_field_filter(queryset, "items[].id", "exact", "1")
        result_ids = set(filtered.values_list("id", flat=True))
        expected_ids = {log1.id, log2.id}
        assert result_ids == expected_ids

    def test_array_field_in_operation_type_conversion(self):
        log1 = self._create_activity_log({"tags": [{"priority": 1}, {"priority": 3}]})
        log2 = self._create_activity_log({"tags": [{"priority": "2"}, {"priority": "1"}]})
        log3 = self._create_activity_log({"tags": [{"priority": "high"}]})

        queryset = ActivityLog.objects.filter(id__in=[log1.id, log2.id, log3.id])

        filtered = self.filter_manager._apply_array_field_filter(queryset, "tags[].priority", "in", ["1", "2"])
        result_ids = set(filtered.values_list("id", flat=True))
        expected_ids = {log1.id, log2.id}
        assert result_ids == expected_ids

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
        assert result_ids == expected_ids


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
        assert result_ids == expected_ids


class TestOptionalBooleanFilters(BaseTest):
    """
    Tests for was_impersonated and is_system optional boolean filters.

    These tests prevent regression of a bug where selecting "All" in the UI
    behaved the same as selecting "No" because:
    1. DRF's BooleanField has default_empty_html=False, causing missing params to become False
    2. The filter logic applied filtering even when the value was None

    The fix involved:
    1. OptionalBooleanField with default_empty_html=None
    2. Filter logic that skips filtering when value is None
    """

    def setUp(self):
        super().setUp()
        self.filter_manager = AdvancedActivityLogFilterManager()

    def test_missing_boolean_params_serialize_to_none_not_false(self):
        """
        When was_impersonated/is_system params are omitted from query string,
        the serializer should return None (not False).

        This catches the DRF default_empty_html=False bug.
        """
        from django.http import QueryDict

        from posthog.api.advanced_activity_logs.viewset import AdvancedActivityLogFiltersSerializer

        query_params = QueryDict("start_date=2024-01-01")
        serializer = AdvancedActivityLogFiltersSerializer(data=query_params)
        serializer.is_valid(raise_exception=True)

        assert serializer.validated_data.get("was_impersonated") is None
        assert serializer.validated_data.get("is_system") is None

    def test_none_filter_values_return_all_records(self):
        """
        When filter dict contains None values (from missing query params),
        no filtering should be applied - all records should be returned.

        This is the "All" option in the UI dropdown.
        """
        log_impersonated = ActivityLog.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            scope="TestScope",
            activity="updated",
            item_id="test",
            detail={},
            was_impersonated=True,
            is_system=True,
        )
        log_normal = ActivityLog.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            scope="TestScope",
            activity="updated",
            item_id="test",
            detail={},
            was_impersonated=False,
            is_system=False,
        )

        queryset = ActivityLog.objects.filter(id__in=[log_impersonated.id, log_normal.id])

        filtered = self.filter_manager.apply_filters(queryset, {"was_impersonated": None, "is_system": None})
        assert filtered.count() == 2
