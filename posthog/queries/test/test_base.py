import datetime
from zoneinfo import ZoneInfo

import unittest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from dateutil import tz

from posthog.models.filters.path_filter import PathFilter
from posthog.queries.base import determine_parsed_incoming_date, relative_date_parse_for_feature_flag_matching


class TestBase(APIBaseTest):
    def test_determine_compared_filter(self):
        from posthog.queries.base import determine_compared_filter

        filter = PathFilter(data={"date_from": "2020-05-23", "date_to": "2020-05-29"}, team=self.team)
        compared_filter = determine_compared_filter(filter)

        self.assertIsInstance(compared_filter, PathFilter)
        self.assertLessEqual(
            {
                "date_from": "2020-05-16T00:00:00+00:00",
                "date_to": "2020-05-22T23:59:59.999999+00:00",
            }.items(),
            compared_filter.to_dict().items(),
        )


class TestDetermineParsedIncomingDate(unittest.TestCase):
    def test_determine_parsed_incoming_date_with_int_timestamp(self):
        self.assertEqual(
            determine_parsed_incoming_date(1836277747), datetime.datetime(2028, 3, 10, 5, 9, 7, tzinfo=ZoneInfo("UTC"))
        )

    def test_determine_parsed_incoming_date_with_float_timestamp(self):
        timestamp = 1836277747.867530
        expected = datetime.datetime(2028, 3, 10, 5, 9, 7, 867530, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(determine_parsed_incoming_date(timestamp), expected)

    def test_determine_parsed_incoming_date_with_string_timestamp(self):
        parsed_date = determine_parsed_incoming_date("1836277747")
        expected = datetime.datetime(2028, 3, 10, 5, 9, 7, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(parsed_date, expected)

    def test_determine_parsed_incoming_date_with_datetime(self):
        parsed_date = determine_parsed_incoming_date(datetime.datetime(2028, 3, 10, 5, 9, 7, tzinfo=ZoneInfo("UTC")))
        expected = datetime.datetime(2028, 3, 10, 5, 9, 7, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(parsed_date, expected)

    def test_determine_parsed_incoming_date_with_string_date(self):
        parsed_date = determine_parsed_incoming_date("2028-03-10T05:09:07Z")
        expected = datetime.datetime(2028, 3, 10, 5, 9, 7, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(parsed_date, expected)

    def test_determine_parsed_date_for_property_matching_with_string_fractional_timestamp(self):
        timestamp = "1836277747.867530"
        expected = datetime.datetime(2028, 3, 10, 5, 9, 7, 867530, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(determine_parsed_incoming_date(timestamp), expected)


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
