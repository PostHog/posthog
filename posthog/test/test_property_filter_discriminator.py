from django.test.testcases import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError

from posthog.schema import (
    AccountCustomPropertyFilter,
    CohortPropertyFilter,
    DashboardFilter,
    DataWarehousePersonPropertyFilter,
    DataWarehousePropertyFilter,
    ElementPropertyFilter,
    EmptyPropertyFilter,
    ErrorTrackingIssueFilter,
    EventMetadataPropertyFilter,
    EventPropertyFilter,
    EventsNode,
    EventsQuery,
    FeaturePropertyFilter,
    FlagPropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    LogEntryPropertyFilter,
    LogPropertyFilter,
    LogPropertyFilterType,
    MetricPropertyFilter,
    PersonMetadataPropertyFilter,
    PersonPropertyFilter,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    RecordingPropertyFilter,
    RevenueAnalyticsPropertyFilter,
    SessionPropertyFilter,
    SpanPropertyFilter,
    SpanPropertyFilterType,
    TrendsQuery,
    WorkflowVariablePropertyFilter,
)


# Mirrors TrendsQueryWithTemplateVariables in filter_to_query.py: subclassing a schema
# model from another module only works if the parent's annotations resolved at class
# creation, i.e. the discriminated aliases were emitted before their usage sites.
class TrendsQuerySubclassedElsewhere(TrendsQuery):
    pass


class TestPropertyFilterDiscriminator(SimpleTestCase):
    # The AnyPropertyFilter union was an undiscriminated smart union — Pydantic walked
    # every member per item, so one malformed filter produced an error per member and
    # valid filters paid for the walk. bin/patch-schema-property-filter-discriminator.py
    # now routes on `type` via the callable in posthog/schema_discriminators.py, which
    # also preserves legacy tolerance: filters without `type`, `{}` rows, multi-value
    # log/span tags, and the AND/OR-tagged recursive group. These tests pin both the
    # routing and the tolerance so a schema regeneration that drops either fails here.

    @parameterized.expand(
        [
            ("event", {"type": "event", "key": "k", "operator": "exact"}, EventPropertyFilter),
            ("person", {"type": "person", "key": "k", "operator": "exact"}, PersonPropertyFilter),
            (
                "person_metadata",
                {"type": "person_metadata", "key": "created_at", "operator": "exact"},
                PersonMetadataPropertyFilter,
            ),
            ("element", {"type": "element", "key": "text", "operator": "exact"}, ElementPropertyFilter),
            (
                "event_metadata",
                {"type": "event_metadata", "key": "distinct_id", "operator": "exact"},
                EventMetadataPropertyFilter,
            ),
            ("session", {"type": "session", "key": "$session_duration", "operator": "gt"}, SessionPropertyFilter),
            ("cohort", {"type": "cohort", "key": "id", "value": 5}, CohortPropertyFilter),
            ("recording", {"type": "recording", "key": "duration", "operator": "gt"}, RecordingPropertyFilter),
            ("log_entry", {"type": "log_entry", "key": "level", "operator": "exact"}, LogEntryPropertyFilter),
            ("group", {"type": "group", "key": "k", "operator": "exact", "group_type_index": 0}, GroupPropertyFilter),
            ("feature", {"type": "feature", "key": "$feature/x", "operator": "exact"}, FeaturePropertyFilter),
            (
                "flag",
                {"type": "flag", "key": "123", "operator": "flag_evaluates_to", "value": True},
                FlagPropertyFilter,
            ),
            ("hogql", {"type": "hogql", "key": "properties.x = 1"}, HogQLPropertyFilter),
            ("empty", {"type": "empty"}, EmptyPropertyFilter),
            (
                "data_warehouse",
                {"type": "data_warehouse", "key": "k", "operator": "exact"},
                DataWarehousePropertyFilter,
            ),
            (
                "data_warehouse_person_property",
                {"type": "data_warehouse_person_property", "key": "k", "operator": "exact"},
                DataWarehousePersonPropertyFilter,
            ),
            (
                "error_tracking_issue",
                {"type": "error_tracking_issue", "key": "k", "operator": "exact"},
                ErrorTrackingIssueFilter,
            ),
            ("log", {"type": "log", "key": "k", "operator": "exact"}, LogPropertyFilter),
            ("metric_attribute", {"type": "metric_attribute", "key": "k", "operator": "exact"}, MetricPropertyFilter),
            ("span", {"type": "span", "key": "k", "operator": "exact"}, SpanPropertyFilter),
            (
                "revenue_analytics",
                {"type": "revenue_analytics", "key": "k", "operator": "exact"},
                RevenueAnalyticsPropertyFilter,
            ),
            (
                "account_custom_property",
                {"type": "account_custom_property", "key": "k", "operator": "exact"},
                AccountCustomPropertyFilter,
            ),
            (
                "workflow_variable",
                {"type": "workflow_variable", "key": "k", "operator": "exact"},
                WorkflowVariablePropertyFilter,
            ),
        ]
    )
    def test_valid_filter_routes_to_declared_type(self, _name: str, payload: dict, expected: type) -> None:
        node = EventsNode(properties=[payload])
        assert node.properties is not None
        assert type(node.properties[0]) is expected

    def test_type_less_filter_with_key_validates_as_event_filter(self) -> None:
        # Filters saved before `type` was consistently written omit it; they must keep
        # validating as event property filters (the historical smart-union outcome).
        dashboard_filter = DashboardFilter(properties=[{"key": "$browser", "value": "Chrome"}])
        assert dashboard_filter.properties is not None
        item = dashboard_filter.properties[0]
        assert type(item) is EventPropertyFilter
        assert item.type == "event"

    def test_empty_filter_row_validates_as_empty_filter(self) -> None:
        dashboard_filter = DashboardFilter(properties=[{}])
        assert dashboard_filter.properties is not None
        assert type(dashboard_filter.properties[0]) is EmptyPropertyFilter

    def test_key_less_value_only_filter_validates_as_cohort_filter(self) -> None:
        # Legacy cohort filters were saved as just {"value": <cohort pk>} and validated
        # as CohortPropertyFilter via its key="id" default.
        node = EventsNode(properties=[{"value": 35}])
        assert node.properties is not None
        item = node.properties[0]
        assert type(item) is CohortPropertyFilter
        assert item.key == "id"
        assert item.value == 35

    @parameterized.expand(
        [
            ("log_attribute", LogPropertyFilter, LogPropertyFilterType.LOG_ATTRIBUTE),
            ("log_resource_attribute", LogPropertyFilter, LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE),
            ("span_attribute", SpanPropertyFilter, SpanPropertyFilterType.SPAN_ATTRIBUTE),
            ("span_resource_attribute", SpanPropertyFilter, SpanPropertyFilterType.SPAN_RESOURCE_ATTRIBUTE),
        ]
    )
    def test_multi_value_tags_route_and_preserve_type(self, tag: str, expected: type, expected_type: object) -> None:
        node = EventsNode(properties=[{"type": tag, "key": "k", "operator": "exact"}])
        assert node.properties is not None
        item = node.properties[0]
        assert type(item) is expected
        assert item.type == expected_type

    def test_property_group_values_recurse(self) -> None:
        group = PropertyGroupFilterValue.model_validate(
            {
                "type": "AND",
                "values": [
                    {"type": "OR", "values": [{"key": "x", "value": "y"}]},
                    {"type": "event", "key": "k", "operator": "exact"},
                ],
            }
        )
        nested = group.values[0]
        assert type(nested) is PropertyGroupFilterValue
        assert type(nested.values[0]) is EventPropertyFilter
        assert type(group.values[1]) is EventPropertyFilter

    def test_insight_properties_accept_list_and_group_forms(self) -> None:
        group_form = TrendsQuery.model_validate(
            {
                "kind": "TrendsQuery",
                "series": [],
                "properties": {"type": "AND", "values": [{"type": "OR", "values": []}]},
            }
        )
        assert type(group_form.properties) is PropertyGroupFilter

        list_form = TrendsQuery.model_validate(
            {
                "kind": "TrendsQuery",
                "series": [],
                "properties": [{"type": "person", "key": "email", "operator": "icontains", "value": "@x.com"}],
            }
        )
        assert isinstance(list_form.properties, list)
        assert type(list_form.properties[0]) is PersonPropertyFilter

    def test_fixed_properties_keep_group_smart_union(self) -> None:
        # EventsQuery.fixedProperties also unions PropertyGroupFilter and
        # PropertyGroupFilterValue, which share the AND/OR tag and stay outside the
        # discriminated alias — group dicts must keep resolving to PropertyGroupFilter.
        query = EventsQuery.model_validate(
            {
                "kind": "EventsQuery",
                "select": ["*"],
                "fixedProperties": [
                    {"type": "AND", "values": [{"type": "AND", "values": []}]},
                    {"type": "event", "key": "k", "operator": "exact"},
                    {},
                ],
            }
        )
        assert query.fixedProperties is not None
        assert type(query.fixedProperties[0]) is PropertyGroupFilter
        assert type(query.fixedProperties[1]) is EventPropertyFilter
        assert type(query.fixedProperties[2]) is EmptyPropertyFilter

    def test_unknown_type_returns_single_clean_tag_error(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            EventsNode(properties=[{"type": "banana", "key": "k"}])

        errors = ctx.exception.errors()
        assert len(errors) == 1, f"expected exactly one error, got {len(errors)}: {errors}"
        assert errors[0]["type"] == "union_tag_invalid"
        expected_tags = errors[0]["ctx"]["expected_tags"]
        for tag in ("'event'", "'cohort'", "'hogql'", "'empty'", "'workflow_variable'"):
            assert tag in expected_tags, f"expected {tag} in {expected_tags!r}"

    def test_invalid_item_reports_errors_only_under_routed_tag(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            EventsNode(properties=[{"type": "event", "value": "v"}])

        errors = ctx.exception.errors()
        assert len(errors) == 1, f"expected exactly one error, got {len(errors)}: {errors}"
        assert errors[0]["type"] == "missing"
        assert errors[0]["loc"] == ("properties", 0, "event", "key")

    def test_malformed_items_produce_one_error_each(self) -> None:
        # Regression for the smart-union error explosion: three malformed items must
        # produce exactly three errors, not one per (item x member x field).
        with self.assertRaises(ValidationError) as ctx:
            EventsNode(
                properties=[
                    {"type": "event", "unexpected": 1, "key": "a"},
                    {"type": "event", "unexpected": 2, "key": "b"},
                    {"type": "event", "unexpected": 3, "key": "c"},
                ]
            )

        errors = ctx.exception.errors()
        assert len(errors) == 3, f"expected exactly one error per item, got {len(errors)}: {errors}"
        assert all(error["type"] == "extra_forbidden" for error in errors)

    def test_subclass_in_another_module_resolves_the_alias(self) -> None:
        query = TrendsQuerySubclassedElsewhere.model_validate(
            {"kind": "TrendsQuery", "series": [], "properties": [{"type": "event", "key": "k", "operator": "exact"}]}
        )
        assert isinstance(query.properties, list)
        assert type(query.properties[0]) is EventPropertyFilter

    def test_serialization_round_trip_is_stable(self) -> None:
        node = EventsNode(
            properties=[
                {"type": "person", "key": "email", "operator": "icontains", "value": "@x.com"},
                {"key": "$browser", "value": "Chrome"},
                {"type": "log_attribute", "key": "k", "operator": "exact"},
            ]
        )
        assert EventsNode.model_validate(node.model_dump(exclude_none=True)) == node
