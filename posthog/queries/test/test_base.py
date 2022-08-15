from django.test import TestCase
from rest_framework.exceptions import ValidationError

from posthog.models.filters.path_filter import PathFilter
from posthog.models.property.property import Property
from posthog.queries.base import match_property
from posthog.test.base import APIBaseTest


class TestBase(APIBaseTest):
    def test_determine_compared_filter(self):
        from posthog.queries.base import determine_compared_filter

        filter = PathFilter(data={"date_from": "2020-05-22", "date_to": "2020-05-29"})
        compared_filter = determine_compared_filter(filter)

        self.assertIsInstance(compared_filter, PathFilter)
        self.assertDictContainsSubset({"date_from": "2020-05-15", "date_to": "2020-05-22",}, compared_filter.to_dict())


class TestMatchProperties(TestCase):
    def test_match_properties_exact(self):
        property_a = Property(key="key", value="value")

        self.assertTrue(match_property(property_a, {"key": "value"}))

        self.assertFalse(match_property(property_a, {"key": "value2"}))
        self.assertFalse(match_property(property_a, {"key": ""}))
        self.assertFalse(match_property(property_a, {"key": None}))

        with self.assertRaises(ValidationError):
            match_property(property_a, {"key2": "value"})
            match_property(property_a, {})

        property_b = Property(key="key", value="value", operator="exact")
        self.assertTrue(match_property(property_b, {"key": "value"}))

        self.assertFalse(match_property(property_b, {"key": "value2"}))

        property_c = Property(key="key", value=["value1", "value2", "value3"], operator="exact")
        self.assertTrue(match_property(property_c, {"key": "value1"}))
        self.assertTrue(match_property(property_c, {"key": "value2"}))
        self.assertTrue(match_property(property_c, {"key": "value3"}))

        self.assertFalse(match_property(property_c, {"key": "value4"}))

        with self.assertRaises(ValidationError):
            match_property(property_c, {"key2": "value"})

    def test_match_properties_not_in(self):
        property_a = Property(key="key", value="value", operator="is_not")
        self.assertTrue(match_property(property_a, {"key": "value2"}))
        self.assertTrue(match_property(property_a, {"key": ""}))
        self.assertTrue(match_property(property_a, {"key": None}))

        property_c = Property(key="key", value=["value1", "value2", "value3"], operator="is_not")
        self.assertTrue(match_property(property_c, {"key": "value4"}))
        self.assertTrue(match_property(property_c, {"key": "value5"}))
        self.assertTrue(match_property(property_c, {"key": "value6"}))
        self.assertTrue(match_property(property_c, {"key": ""}))
        self.assertTrue(match_property(property_c, {"key": None}))

        self.assertFalse(match_property(property_c, {"key": "value2"}))
        self.assertFalse(match_property(property_c, {"key": "value3"}))
        self.assertFalse(match_property(property_c, {"key": "value1"}))

        with self.assertRaises(ValidationError):
            match_property(property_a, {"key2": "value"})
            match_property(property_c, {"key2": "value1"})  # overrides don't have 'key'

    def test_match_properties_is_set(self):
        property_a = Property(key="key", operator="is_set")
        self.assertTrue(match_property(property_a, {"key": "value"}))
        self.assertTrue(match_property(property_a, {"key": "value2"}))
        self.assertTrue(match_property(property_a, {"key": ""}))
        self.assertTrue(match_property(property_a, {"key": None}))

        with self.assertRaises(ValidationError):
            match_property(property_a, {"key2": "value"})
            match_property(property_a, {})

    def test_match_properties_icontains(self):
        property_a = Property(key="key", value="valUe", operator="icontains")
        self.assertTrue(match_property(property_a, {"key": "value"}))
        self.assertTrue(match_property(property_a, {"key": "value2"}))
        self.assertTrue(match_property(property_a, {"key": "value3"}))
        self.assertTrue(match_property(property_a, {"key": "vaLue4"}))
        self.assertTrue(match_property(property_a, {"key": "343tfvalue5"}))

        self.assertFalse(match_property(property_a, {"key": "Alakazam"}))
        self.assertFalse(match_property(property_a, {"key": 123}))

        property_b = Property(key="key", value="3", operator="icontains")
        self.assertTrue(match_property(property_b, {"key": "3"}))
        self.assertTrue(match_property(property_b, {"key": 323}))
        self.assertTrue(match_property(property_b, {"key": "val3"}))

        self.assertFalse(match_property(property_b, {"key": "three"}))

    def test_match_properties_regex(self):
        property_a = Property(key="key", value=r"\.com$", operator="regex")
        self.assertTrue(match_property(property_a, {"key": "value.com"}))
        self.assertTrue(match_property(property_a, {"key": "value2.com"}))

        self.assertFalse(match_property(property_a, {"key": ".com343tfvalue5"}))
        self.assertFalse(match_property(property_a, {"key": "Alakazam"}))
        self.assertFalse(match_property(property_a, {"key": 123}))

        property_b = Property(key="key", value="3", operator="regex")
        self.assertTrue(match_property(property_b, {"key": "3"}))
        self.assertTrue(match_property(property_b, {"key": 323}))
        self.assertTrue(match_property(property_b, {"key": "val3"}))

        self.assertFalse(match_property(property_b, {"key": "three"}))

        # invalid regex
        property_c = Property(key="key", value=r"?*", operator="regex")
        self.assertFalse(match_property(property_c, {"key": "value"}))
        self.assertFalse(match_property(property_c, {"key": "value2"}))

        # non string value
        property_d = Property(key="key", value=4, operator="regex")
        self.assertTrue(match_property(property_d, {"key": "4"}))
        self.assertTrue(match_property(property_d, {"key": 4}))

        self.assertFalse(match_property(property_d, {"key": "value"}))

    def test_match_properties_math_operators(self):
        property_a = Property(key="key", value=1, operator="gt")
        self.assertTrue(match_property(property_a, {"key": 2}))
        self.assertTrue(match_property(property_a, {"key": 3}))

        self.assertFalse(match_property(property_a, {"key": 0}))
        self.assertFalse(match_property(property_a, {"key": -1}))
        self.assertFalse(match_property(property_a, {"key": "23"}))

        property_b = Property(key="key", value=1, operator="lt")
        self.assertTrue(match_property(property_b, {"key": 0}))
        self.assertTrue(match_property(property_b, {"key": -1}))
        self.assertTrue(match_property(property_b, {"key": -3}))

        self.assertFalse(match_property(property_b, {"key": 1}))
        self.assertFalse(match_property(property_b, {"key": "1"}))
        self.assertFalse(match_property(property_b, {"key": "3"}))

        property_c = Property(key="key", value=1, operator="gte")
        self.assertTrue(match_property(property_c, {"key": 1}))
        self.assertTrue(match_property(property_c, {"key": 2}))

        self.assertFalse(match_property(property_c, {"key": 0}))
        self.assertFalse(match_property(property_c, {"key": -1}))
        self.assertFalse(match_property(property_c, {"key": "3"}))

        property_d = Property(key="key", value="43", operator="lt")
        self.assertTrue(match_property(property_d, {"key": "41"}))
        self.assertTrue(match_property(property_d, {"key": "42"}))

        self.assertFalse(match_property(property_d, {"key": "43"}))
        self.assertFalse(match_property(property_d, {"key": "44"}))
        self.assertFalse(match_property(property_d, {"key": 44}))
