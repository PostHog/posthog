from ee.hogai.summarizers.property_filters import PropertyFilterDescriber, retrieve_hardcoded_taxonomy
from posthog.schema import (
    ElementPropertyFilter,
    EventPropertyFilter,
    FeaturePropertyFilter,
    HogQLPropertyFilter,
    PersonPropertyFilter,
    PropertyOperator,
    SessionPropertyFilter,
)
from posthog.test.base import BaseTest


class TestPropertyFilterDescriber(BaseTest):
    def test_event_property_filter(self):
        # No taxonomy
        filter = EventPropertyFilter(key="prop", operator="exact", value="test")
        descriptor = PropertyFilterDescriber(filter=filter)
        self.assertEqual(descriptor.description, "Event property `prop` matches exactly `test`")
        self.assertFalse(descriptor.taxonomy)

        # With taxonomy
        filter = EventPropertyFilter(key="$current_url", operator="icontains", value="url")
        descriptor = PropertyFilterDescriber(filter=filter)
        self.assertEqual(descriptor.description, "Event property `$current_url` contains `url`")
        prop = descriptor.taxonomy
        self.assertEqual(prop.group, "event_properties")
        self.assertEqual(prop.key, "$current_url")
        self.assertIsNotNone(prop.description)

    def test_person_property_filter(self):
        # No taxonomy
        filter = PersonPropertyFilter(key="prop", operator="exact", value="test")
        descriptor = PropertyFilterDescriber(filter=filter)
        self.assertEqual(descriptor.description, "Person property `prop` matches exactly `test`")
        self.assertFalse(descriptor.taxonomy)

        # With taxonomy
        filter = PersonPropertyFilter(key="email", operator="icontains", value="example.com")
        descriptor = PropertyFilterDescriber(filter=filter)
        self.assertEqual(descriptor.description, "Person property `email` contains `example.com`")
        prop = descriptor.taxonomy
        if prop:  # Only check taxonomy if it exists
            self.assertEqual(prop.group, "person_properties")
            self.assertEqual(prop.key, "email")
            self.assertIsNotNone(prop.description)

    def test_element_property_filter(self):
        filter = ElementPropertyFilter(key="tag_name", operator="exact", value="button")
        descriptor = PropertyFilterDescriber(filter=filter)
        self.assertEqual(descriptor.description, "Element property `tag_name` matches exactly `button`")
        prop = descriptor.taxonomy
        self.assertEqual(prop.group, "element_properties")
        self.assertEqual(prop.key, "tag_name")
        self.assertIsNotNone(prop.description)

    def test_session_property_filter(self):
        filter = SessionPropertyFilter(key="$session_duration", operator="gt", value=300)
        descriptor = PropertyFilterDescriber(filter=filter)
        self.assertEqual(descriptor.description, "Session property `$session_duration` greater than `300`")
        prop = descriptor.taxonomy
        self.assertEqual(prop.group, "session_properties")
        self.assertEqual(prop.key, "$session_duration")
        self.assertIsNotNone(prop.description)

    def test_feature_property_filter(self):
        filter = FeaturePropertyFilter(key="$feature/abc", operator="exact", value="true")
        descriptor = PropertyFilterDescriber(filter=filter)
        self.assertEqual(descriptor.description, "Enrollment of the feature `$feature/abc` matches exactly `true`")
        self.assertFalse(descriptor.taxonomy)  # Feature property doesn't have taxonomy

    def test_hogql_property_filter(self):
        filter = HogQLPropertyFilter(key="'url' in properties.$current_url")
        descriptor = PropertyFilterDescriber(filter=filter)
        self.assertEqual(
            descriptor.description,
            "Matches the SQL filter `'url' in properties.$current_url`",
        )
        self.assertFalse(descriptor.taxonomy)  # HogQL property doesn't have taxonomy

    def test_float_value_formatting(self):
        # Test that floats with trailing zeros are displayed as integers
        filter = EventPropertyFilter(key="value", operator="gt", value=300.0)
        descriptor = PropertyFilterDescriber(filter=filter)
        self.assertEqual(descriptor.description, "Event property `value` greater than `300`")

        # Test that floats with decimal parts are preserved
        filter = EventPropertyFilter(key="value", operator="gt", value=300.5)
        descriptor = PropertyFilterDescriber(filter=filter)
        self.assertEqual(descriptor.description, "Event property `value` greater than `300.5`")

    def test_retrieve_hardcoded_taxonomy(self):
        # Test retrieval for existing taxonomy group and key
        result1 = retrieve_hardcoded_taxonomy("events", "$pageview")
        self.assertIsNotNone(result1)

        # Test returns None for existing taxonomy group but non-existent key
        result2 = retrieve_hardcoded_taxonomy("events", "random")
        self.assertIsNone(result2)

        # Test returns None for non-existent taxonomy group
        result3 = retrieve_hardcoded_taxonomy("test", "test")
        self.assertIsNone(result3)

    def test_all_operators_are_supported(self):
        for operator in PropertyOperator:
            filter = EventPropertyFilter(key="prop", operator=operator, value="test")
            descriptor = PropertyFilterDescriber(filter=filter)
            self.assertIsNotNone(descriptor.description)
