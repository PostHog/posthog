import pytest
from posthog.test.base import BaseTest

from posthog.schema import (
    DataWarehousePropertyFilter,
    ElementPropertyFilter,
    EventPropertyFilter,
    FeaturePropertyFilter,
    HogQLPropertyFilter,
    PersonPropertyFilter,
    PropertyOperator,
    SessionPropertyFilter,
)

from ee.hogai.summarizers.property_filters import (
    PropertyFilterCollectionDescriber,
    PropertyFilterDescriber,
    retrieve_hardcoded_taxonomy,
)


class TestPropertyFilterDescriber(BaseTest):
    def test_event_property_filter(self):
        # No taxonomy
        filter = EventPropertyFilter(key="prop", operator="exact", value="test")
        descriptor = PropertyFilterDescriber(filter=filter)
        assert descriptor.description == "event property `prop` matches exactly `test`"
        assert not descriptor.taxonomy

        # With taxonomy
        filter = EventPropertyFilter(key="$current_url", operator="icontains", value="url")
        descriptor = PropertyFilterDescriber(filter=filter)
        assert descriptor.description == "event property `$current_url` contains `url`"
        prop = descriptor.taxonomy
        assert prop is not None
        assert prop.group == "event_properties"
        assert prop.key == "$current_url"
        assert prop.description is not None

    def test_event_property_filter_is_not_set(self):
        # Test with is_not_set operator and null value
        filter = EventPropertyFilter(key="property_name", operator=PropertyOperator.IS_NOT_SET, value=None)
        descriptor = PropertyFilterDescriber(filter=filter)
        assert descriptor.description == "event property `property_name` is not set"
        assert not descriptor.taxonomy

    def test_person_property_filter(self):
        # No taxonomy
        filter = PersonPropertyFilter(key="prop", operator="exact", value="test")
        descriptor = PropertyFilterDescriber(filter=filter)
        assert descriptor.description == "person property `prop` matches exactly `test`"
        assert not descriptor.taxonomy

        # With taxonomy
        filter = PersonPropertyFilter(key="email", operator="icontains", value="example.com")
        descriptor = PropertyFilterDescriber(filter=filter)
        assert descriptor.description == "person property `email` contains `example.com`"
        prop = descriptor.taxonomy
        if prop:  # Only check taxonomy if it exists
            assert prop.group == "person_properties"
            assert prop.key == "email"
            assert prop.description is not None

    def test_element_property_filter(self):
        filter = ElementPropertyFilter(key="tag_name", operator="exact", value="button")
        descriptor = PropertyFilterDescriber(filter=filter)
        assert descriptor.description == "element property `tag_name` matches exactly `button`"
        prop = descriptor.taxonomy
        assert prop is not None
        assert prop.group == "element_properties"
        assert prop.key == "tag_name"
        assert prop.description is not None

    def test_session_property_filter(self):
        filter = SessionPropertyFilter(key="$session_duration", operator="gt", value=300)
        descriptor = PropertyFilterDescriber(filter=filter)
        assert descriptor.description == "session property `$session_duration` greater than `300`"
        prop = descriptor.taxonomy
        assert prop is not None
        assert prop.group == "session_properties"
        assert prop.key == "$session_duration"
        assert prop.description is not None

    def test_feature_property_filter(self):
        filter = FeaturePropertyFilter(key="$feature/abc", operator="exact", value="true")
        descriptor = PropertyFilterDescriber(filter=filter)
        assert descriptor.description == "enrollment of the feature `$feature/abc` matches exactly `true`"
        assert not descriptor.taxonomy  # Feature property doesn't have taxonomy

    def test_hogql_property_filter(self):
        filter = HogQLPropertyFilter(key="'url' in properties.$current_url")
        descriptor = PropertyFilterDescriber(filter=filter)
        assert descriptor.description == "matches the SQL filter `'url' in properties.$current_url`"
        assert not descriptor.taxonomy  # HogQL property doesn't have taxonomy

    def test_float_value_formatting(self):
        # Test that floats with trailing zeros are displayed as integers
        filter = EventPropertyFilter(key="value", operator="gt", value=300.0)
        descriptor = PropertyFilterDescriber(filter=filter)
        assert descriptor.description == "event property `value` greater than `300`"

        # Test that floats with decimal parts are preserved
        filter = EventPropertyFilter(key="value", operator="gt", value=300.5)
        descriptor = PropertyFilterDescriber(filter=filter)
        assert descriptor.description == "event property `value` greater than `300.5`"

    def test_retrieve_hardcoded_taxonomy(self):
        # Test retrieval for existing taxonomy group and key
        result1 = retrieve_hardcoded_taxonomy("events", "$pageview")
        assert result1 is not None

        # Test returns None for existing taxonomy group but non-existent key
        result2 = retrieve_hardcoded_taxonomy("events", "random")
        assert result2 is None

        # Test returns None for non-existent taxonomy group
        result3 = retrieve_hardcoded_taxonomy("test", "test")
        assert result3 is None

    def test_all_operators_are_supported(self):
        for operator in PropertyOperator:
            filter = EventPropertyFilter(key="prop", operator=operator, value="test")
            descriptor = PropertyFilterDescriber(filter=filter)
            assert descriptor.description is not None

    def test_datawarehouse_property_filter_raises_error(self):
        # Test that a ValueError is raised for DataWarehousePropertyFilter
        filter = DataWarehousePropertyFilter(key="dw_prop", operator="exact", value="test")
        descriptor = PropertyFilterDescriber(filter=filter)
        with pytest.raises(ValueError) as context:
            _ = descriptor.description

        assert "Unknown filter type:" in str(context.value)
        assert "DataWarehousePropertyFilter" in str(context.value)


class TestPropertyFilterCollectionDescriber(BaseTest):
    def test_multiple_property_filters(self):
        # Create filters
        event_filter = EventPropertyFilter(key="$current_url", operator=PropertyOperator.NOT_ICONTAINS, value="url")
        person_filter = PersonPropertyFilter(key="name", operator=PropertyOperator.IS_SET)

        # Create describer with multiple filters
        collection_describer = PropertyFilterCollectionDescriber(filters=[event_filter, person_filter])

        # Get description and taxonomy
        description, taxonomy = collection_describer.describe()

        # Check description
        assert description == "event property `$current_url` doesn't contain `url` AND person property `name` is set"

        # Check taxonomy
        assert len(taxonomy) == 1  # Only $current_url should have taxonomy, not name

        # Convert taxonomy to list for easier assertion
        taxonomy_list = list(taxonomy)
        assert taxonomy_list[0].group == "event_properties"
        assert taxonomy_list[0].key == "$current_url"
        assert taxonomy_list[0].description is not None

    def test_duplicate_property_filters_collapse_taxonomy(self):
        # Create two filters with the same property key but different operators/values
        event_filter1 = EventPropertyFilter(
            key="$current_url", operator=PropertyOperator.ICONTAINS, value="example.com"
        )
        event_filter2 = EventPropertyFilter(key="$current_url", operator=PropertyOperator.NOT_ICONTAINS, value="login")

        # Create describer with the duplicate filters
        collection_describer = PropertyFilterCollectionDescriber(filters=[event_filter1, event_filter2])

        # Get description and taxonomy
        description, taxonomy = collection_describer.describe()

        # Check description contains both filters
        assert (
            description
            == "event property `$current_url` contains `example.com` AND event property `$current_url` doesn't contain `login`"
        )

        # Check taxonomy only has one entry for $current_url despite having two filters with that key
        assert len(taxonomy) == 1

        # Convert taxonomy to list for easier assertion
        taxonomy_entry = next(iter(taxonomy))
        assert taxonomy_entry.group == "event_properties"
        assert taxonomy_entry.key == "$current_url"
        assert taxonomy_entry.description is not None
