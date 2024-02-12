import datetime
import re
import unittest
from unittest.mock import patch

from dateutil import parser, tz
from django.test import TestCase
from freezegun import freeze_time
import pytest
from rest_framework.exceptions import ValidationError

from posthog.models.filters.path_filter import PathFilter
from posthog.models.property.property import Property
from posthog.queries.base import match_property, relative_date_parse_for_feature_flag_matching, sanitize_property_key
from posthog.test.base import APIBaseTest


class TestBase(APIBaseTest):
    def test_determine_compared_filter(self):
        from posthog.queries.base import determine_compared_filter

        filter = PathFilter(data={"date_from": "2020-05-23", "date_to": "2020-05-29"}, team=self.team)
        compared_filter = determine_compared_filter(filter)

        self.assertIsInstance(compared_filter, PathFilter)
        self.assertDictContainsSubset(
            {
                "date_from": "2020-05-16T00:00:00+00:00",
                "date_to": "2020-05-22T23:59:59.999999+00:00",
            },
            compared_filter.to_dict(),
        )


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

        # ensure regex compilation happens only once. to do this, we mock out re.compile,
        # and make the return value of the mock match what the actual function would return.
        # this allows us to intercept the call and assert that it was called exactly once.
        property_e = Property(key="key", value=5, operator="regex")
        pattern = re.compile("5")
        with patch("re.compile") as mock_compile:
            mock_compile.return_value = pattern
            self.assertTrue(match_property(property_e, {"key": "5"}))

        mock_compile.assert_called_once_with("5")

    def test_match_properties_math_operators(self):
        property_a = Property(key="key", value=1, operator="gt")
        self.assertTrue(match_property(property_a, {"key": 2}))
        self.assertTrue(match_property(property_a, {"key": 3}))

        self.assertFalse(match_property(property_a, {"key": 0}))
        self.assertFalse(match_property(property_a, {"key": -1}))
        # now we handle type mismatches so this should be true
        self.assertTrue(match_property(property_a, {"key": "23"}))

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
        # now we handle type mismatches so this should be true
        self.assertTrue(match_property(property_c, {"key": "3"}))

        property_d = Property(key="key", value="43", operator="lt")
        self.assertTrue(match_property(property_d, {"key": "41"}))
        self.assertTrue(match_property(property_d, {"key": "42"}))
        self.assertTrue(match_property(property_d, {"key": 42}))

        self.assertFalse(match_property(property_d, {"key": "43"}))
        self.assertFalse(match_property(property_d, {"key": "44"}))
        self.assertFalse(match_property(property_d, {"key": 44}))

        property_e = Property(key="key", value="30", operator="lt")
        self.assertTrue(match_property(property_e, {"key": "29"}))

        # depending on the type of override, we adjust type comparison
        self.assertTrue(match_property(property_e, {"key": "100"}))
        self.assertFalse(match_property(property_e, {"key": 100}))

        property_f = Property(key="key", value="123aloha", operator="gt")
        self.assertFalse(match_property(property_f, {"key": "123"}))
        self.assertFalse(match_property(property_f, {"key": 122}))

        # this turns into a string comparison
        self.assertTrue(match_property(property_f, {"key": 129}))

    def test_match_property_date_operators(self):
        property_a = Property(key="key", value="2022-05-01", operator="is_date_before")
        self.assertTrue(match_property(property_a, {"key": "2022-03-01"}))
        self.assertTrue(match_property(property_a, {"key": "2022-04-30"}))
        self.assertTrue(match_property(property_a, {"key": datetime.date(2022, 4, 30)}))
        self.assertTrue(match_property(property_a, {"key": datetime.datetime(2022, 4, 30, 1, 2, 3)}))
        self.assertTrue(
            match_property(
                property_a,
                {"key": datetime.datetime(2022, 4, 30, 1, 2, 3, tzinfo=tz.gettz("Europe/Madrid"))},
            )
        )
        self.assertTrue(match_property(property_a, {"key": parser.parse("2022-04-30")}))
        self.assertFalse(match_property(property_a, {"key": "2022-05-30"}))

        # Can't be a number
        self.assertFalse(match_property(property_a, {"key": 1}))

        # can't be invalid string
        self.assertFalse(match_property(property_a, {"key": "abcdef"}))

        property_b = Property(key="key", value="2022-05-01", operator="is_date_after")
        self.assertTrue(match_property(property_b, {"key": "2022-05-02"}))
        self.assertTrue(match_property(property_b, {"key": "2022-05-30"}))
        self.assertTrue(match_property(property_b, {"key": datetime.datetime(2022, 5, 30)}))
        self.assertTrue(match_property(property_b, {"key": parser.parse("2022-05-30")}))
        self.assertFalse(match_property(property_b, {"key": "2022-04-30"}))

        # can't be invalid string
        self.assertFalse(match_property(property_b, {"key": "abcdef"}))

        # Invalid flag property
        property_c = Property(key="key", value=1234, operator="is_date_before")

        self.assertFalse(match_property(property_c, {"key": 1}))
        self.assertFalse(match_property(property_c, {"key": "2022-05-30"}))

        # Timezone aware property
        property_d = Property(key="key", value="2022-04-05 12:34:12 BST", operator="is_date_before")
        self.assertFalse(match_property(property_d, {"key": "2022-05-30"}))

        self.assertTrue(match_property(property_d, {"key": "2022-03-30"}))
        self.assertTrue(match_property(property_d, {"key": "2022-04-05 12:34:11 BST"}))
        self.assertTrue(match_property(property_d, {"key": "2022-04-05 12:34:11 CET"}))

        self.assertFalse(match_property(property_d, {"key": "2022-04-05 12:34:13 CET"}))

    @freeze_time("2022-05-01")
    def test_match_property_relative_date_operators(self):
        property_a = Property(key="key", value="6h", operator="is_date_before")
        self.assertTrue(match_property(property_a, {"key": "2022-03-01"}))
        self.assertTrue(match_property(property_a, {"key": "2022-04-30"}))
        self.assertTrue(match_property(property_a, {"key": datetime.datetime(2022, 4, 30, 1, 2, 3)}))
        # false because date comparison, instead of datetime, so reduces to same date
        self.assertFalse(match_property(property_a, {"key": datetime.date(2022, 4, 30)}))

        self.assertFalse(match_property(property_a, {"key": datetime.datetime(2022, 4, 30, 19, 2, 3)}))
        self.assertTrue(
            match_property(
                property_a,
                {"key": datetime.datetime(2022, 4, 30, 1, 2, 3, tzinfo=tz.gettz("Europe/Madrid"))},
            )
        )
        self.assertTrue(match_property(property_a, {"key": parser.parse("2022-04-30")}))
        self.assertFalse(match_property(property_a, {"key": "2022-05-30"}))

        # Can't be a number
        self.assertFalse(match_property(property_a, {"key": 1}))

        # can't be invalid string
        self.assertFalse(match_property(property_a, {"key": "abcdef"}))

        property_b = Property(key="key", value="1h", operator="is_date_after")
        self.assertTrue(match_property(property_b, {"key": "2022-05-02"}))
        self.assertTrue(match_property(property_b, {"key": "2022-05-30"}))
        self.assertTrue(match_property(property_b, {"key": datetime.datetime(2022, 5, 30)}))
        self.assertTrue(match_property(property_b, {"key": parser.parse("2022-05-30")}))
        self.assertFalse(match_property(property_b, {"key": "2022-04-30"}))

        # can't be invalid string
        self.assertFalse(match_property(property_b, {"key": "abcdef"}))

        # Invalid flag property
        property_c = Property(key="key", value=1234, operator="is_date_after")

        self.assertFalse(match_property(property_c, {"key": 1}))
        self.assertTrue(match_property(property_c, {"key": "2022-05-30"}))

        # # Timezone aware property
        property_d = Property(key="key", value="12d", operator="is_date_before")
        self.assertFalse(match_property(property_d, {"key": "2022-05-30"}))

        self.assertTrue(match_property(property_d, {"key": "2022-03-30"}))
        self.assertTrue(match_property(property_d, {"key": "2022-04-05 12:34:11+01:00"}))
        self.assertTrue(match_property(property_d, {"key": "2022-04-19 01:34:11+02:00"}))

        self.assertFalse(match_property(property_d, {"key": "2022-04-19 02:00:01+02:00"}))

        # Try all possible relative dates
        property_e = Property(key="key", value="1h", operator="is_date_before")
        self.assertFalse(match_property(property_e, {"key": "2022-05-01 00:00:00"}))
        self.assertTrue(match_property(property_e, {"key": "2022-04-30 22:00:00"}))

        property_f = Property(key="key", value="-1d", operator="is_date_before")
        self.assertTrue(match_property(property_f, {"key": "2022-04-29 23:59:00"}))
        self.assertFalse(match_property(property_f, {"key": "2022-04-30 00:00:01"}))

        property_g = Property(key="key", value="1w", operator="is_date_before")
        self.assertTrue(match_property(property_g, {"key": "2022-04-23 00:00:00"}))
        self.assertFalse(match_property(property_g, {"key": "2022-04-24 00:00:00"}))
        self.assertFalse(match_property(property_g, {"key": "2022-04-24 00:00:01"}))

        property_h = Property(key="key", value="1m", operator="is_date_before")
        self.assertTrue(match_property(property_h, {"key": "2022-03-01 00:00:00"}))
        self.assertFalse(match_property(property_h, {"key": "2022-04-05 00:00:00"}))

        property_i = Property(key="key", value="1y", operator="is_date_before")
        self.assertTrue(match_property(property_i, {"key": "2021-04-28 00:00:00"}))
        self.assertFalse(match_property(property_i, {"key": "2021-05-01 00:00:01"}))

        property_j = Property(key="key", value="-122h", operator="is_date_after")
        self.assertTrue(match_property(property_j, {"key": "2022-05-01 00:00:00"}))
        self.assertFalse(match_property(property_j, {"key": "2022-04-23 01:00:00"}))

        property_k = Property(key="key", value="2d", operator="is_date_after")
        self.assertTrue(match_property(property_k, {"key": "2022-05-01 00:00:00"}))
        self.assertTrue(match_property(property_k, {"key": "2022-04-29 00:00:01"}))
        self.assertFalse(match_property(property_k, {"key": "2022-04-29 00:00:00"}))

        property_l = Property(key="key", value="02w", operator="is_date_after")
        self.assertTrue(match_property(property_l, {"key": "2022-05-01 00:00:00"}))
        self.assertFalse(match_property(property_l, {"key": "2022-04-16 00:00:00"}))

        property_m = Property(key="key", value="-1m", operator="is_date_after")
        self.assertTrue(match_property(property_m, {"key": "2022-04-01 00:00:01"}))
        self.assertFalse(match_property(property_m, {"key": "2022-04-01 00:00:00"}))

        property_n = Property(key="key", value="1y", operator="is_date_after")
        self.assertTrue(match_property(property_n, {"key": "2022-05-01 00:00:00"}))
        self.assertTrue(match_property(property_n, {"key": "2021-05-01 00:00:01"}))
        self.assertFalse(match_property(property_n, {"key": "2021-05-01 00:00:00"}))
        self.assertFalse(match_property(property_n, {"key": "2021-04-30 00:00:00"}))
        self.assertFalse(match_property(property_n, {"key": "2021-03-01 12:13:00"}))

    def test_none_property_value_with_all_operators(self):
        property_a = Property(key="key", value="none", operator="is_not")
        self.assertFalse(match_property(property_a, {"key": None}))
        self.assertTrue(match_property(property_a, {"key": "non"}))

        property_b = Property(key="key", value=None, operator="is_set")
        self.assertTrue(match_property(property_b, {"key": None}))

        property_c = Property(key="key", value="no", operator="icontains")
        self.assertTrue(match_property(property_c, {"key": None}))
        self.assertFalse(match_property(property_c, {"key": "smh"}))

        property_d = Property(key="key", value="No", operator="regex")
        self.assertTrue(match_property(property_d, {"key": None}))

        property_d_lower_case = Property(key="key", value="no", operator="regex")
        self.assertFalse(match_property(property_d_lower_case, {"key": None}))

        property_e = Property(key="key", value=1, operator="gt")
        self.assertTrue(match_property(property_e, {"key": None}))

        property_f = Property(key="key", value=1, operator="lt")
        self.assertFalse(match_property(property_f, {"key": None}))

        property_g = Property(key="key", value="xyz", operator="gte")
        self.assertFalse(match_property(property_g, {"key": None}))

        property_h = Property(key="key", value="Oo", operator="lte")
        self.assertTrue(match_property(property_h, {"key": None}))

        property_i = Property(key="key", value="2022-05-01", operator="is_date_before")
        self.assertFalse(match_property(property_i, {"key": None}))

        property_j = Property(key="key", value="2022-05-01", operator="is_date_after")
        self.assertFalse(match_property(property_j, {"key": None}))

        property_k = Property(key="key", value="2022-05-01", operator="is_date_before")
        self.assertFalse(match_property(property_k, {"key": "random"}))


@pytest.mark.parametrize(
    "key,expected",
    [
        ("test_key", "testkey_00942f4668670f3"),
        ("test-key", "testkey_3acfb2c2b433c0e"),
        ("test-!!key", "testkey_007a0fef83e9d2f"),
        ("test-key-1", "testkey1_1af855c78902ffc"),
        ("test-key-1-2", "testkey12_2f0c347f439af5c"),
        ("test-key-1-2-3-4", "testkey1234_0332a83ad5c75ee"),
        ("only_nums!!!;$£hebfjhvd", "onlynumshebfjhvd_5a1514bfab83040"),
        (" ", "_b858cb282617fb0"),
        ("", "_da39a3ee5e6b4b0"),
        ("readme.md", "readmemd_275d783e2982285"),
        ("readme≥md", "readmemd_8857015efe59db9"),
        (None, "None_6eef6648406c333"),
        (12, "12_7b52009b64fd0a2"),
    ],
)
def test_sanitize_keys(key, expected):
    sanitized_key = sanitize_property_key(key)

    assert sanitized_key == expected


class TestRelativeDateParsing(unittest.TestCase):
    def test_invalid_input(self):
        with freeze_time("2020-01-01T12:01:20.1340Z"):
            assert relative_date_parse_for_feature_flag_matching("1") is None
            assert relative_date_parse_for_feature_flag_matching("1x") is None
            assert relative_date_parse_for_feature_flag_matching("1.2y") is None
            assert relative_date_parse_for_feature_flag_matching("1z") is None
            assert relative_date_parse_for_feature_flag_matching("1s") is None
            assert relative_date_parse_for_feature_flag_matching("123344000.134m") is None
            assert relative_date_parse_for_feature_flag_matching("bazinga") is None
            assert relative_date_parse_for_feature_flag_matching("000bello") is None
            assert relative_date_parse_for_feature_flag_matching("000hello") is None

            assert relative_date_parse_for_feature_flag_matching("000h") is not None
            assert relative_date_parse_for_feature_flag_matching("1000h") is not None

    def test_overflow(self):
        assert relative_date_parse_for_feature_flag_matching("1000000h") is None
        assert relative_date_parse_for_feature_flag_matching("100000000000000000y") is None

    def test_hour_parsing(self):
        with freeze_time("2020-01-01T12:01:20.1340Z"):
            assert relative_date_parse_for_feature_flag_matching("1h") == datetime.datetime(
                2020, 1, 1, 11, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("2h") == datetime.datetime(
                2020, 1, 1, 10, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("24h") == datetime.datetime(
                2019, 12, 31, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("30h") == datetime.datetime(
                2019, 12, 31, 6, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("48h") == datetime.datetime(
                2019, 12, 30, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )

            assert relative_date_parse_for_feature_flag_matching(
                "24h"
            ) == relative_date_parse_for_feature_flag_matching("1d")
            assert relative_date_parse_for_feature_flag_matching(
                "48h"
            ) == relative_date_parse_for_feature_flag_matching("2d")

    def test_day_parsing(self):
        with freeze_time("2020-01-01T12:01:20.1340Z"):
            assert relative_date_parse_for_feature_flag_matching("1d") == datetime.datetime(
                2019, 12, 31, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("2d") == datetime.datetime(
                2019, 12, 30, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("7d") == datetime.datetime(
                2019, 12, 25, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("14d") == datetime.datetime(
                2019, 12, 18, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("30d") == datetime.datetime(
                2019, 12, 2, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )

            assert relative_date_parse_for_feature_flag_matching("7d") == relative_date_parse_for_feature_flag_matching(
                "1w"
            )

    def test_week_parsing(self):
        with freeze_time("2020-01-01T12:01:20.1340Z"):
            assert relative_date_parse_for_feature_flag_matching("1w") == datetime.datetime(
                2019, 12, 25, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("2w") == datetime.datetime(
                2019, 12, 18, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("4w") == datetime.datetime(
                2019, 12, 4, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("8w") == datetime.datetime(
                2019, 11, 6, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )

            assert relative_date_parse_for_feature_flag_matching("1m") == datetime.datetime(
                2019, 12, 1, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("4w") != relative_date_parse_for_feature_flag_matching(
                "1m"
            )

    def test_month_parsing(self):
        with freeze_time("2020-01-01T12:01:20.1340Z"):
            assert relative_date_parse_for_feature_flag_matching("1m") == datetime.datetime(
                2019, 12, 1, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("2m") == datetime.datetime(
                2019, 11, 1, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("4m") == datetime.datetime(
                2019, 9, 1, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("8m") == datetime.datetime(
                2019, 5, 1, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )

            assert relative_date_parse_for_feature_flag_matching("1y") == datetime.datetime(
                2019, 1, 1, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching(
                "12m"
            ) == relative_date_parse_for_feature_flag_matching("1y")

        with freeze_time("2020-04-03T00:00:00"):
            assert relative_date_parse_for_feature_flag_matching("1m") == datetime.datetime(
                2020, 3, 3, 0, 0, 0, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("2m") == datetime.datetime(
                2020, 2, 3, 0, 0, 0, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("4m") == datetime.datetime(
                2019, 12, 3, 0, 0, 0, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("8m") == datetime.datetime(
                2019, 8, 3, 0, 0, 0, tzinfo=tz.gettz("UTC")
            )

            assert relative_date_parse_for_feature_flag_matching("1y") == datetime.datetime(
                2019, 4, 3, 0, 0, 0, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching(
                "12m"
            ) == relative_date_parse_for_feature_flag_matching("1y")

    def test_year_parsing(self):
        with freeze_time("2020-01-01T12:01:20.1340Z"):
            assert relative_date_parse_for_feature_flag_matching("1y") == datetime.datetime(
                2019, 1, 1, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("2y") == datetime.datetime(
                2018, 1, 1, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("4y") == datetime.datetime(
                2016, 1, 1, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
            assert relative_date_parse_for_feature_flag_matching("8y") == datetime.datetime(
                2012, 1, 1, 12, 1, 20, 134000, tzinfo=tz.gettz("UTC")
            )
