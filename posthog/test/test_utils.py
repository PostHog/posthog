from typing import Any, List, Optional, Sequence, Tuple
from unittest.mock import call, patch

from django.http import HttpRequest
from django.test import TestCase
from django.test.client import RequestFactory
from freezegun import freeze_time
from rest_framework.request import Request

from posthog.api.test.mock_sentry import mock_sentry_context_for_tagging
from posthog.exceptions import RequestParsingError
from posthog.models import EventDefinition
from posthog.test.base import BaseTest
from posthog.utils import (
    format_query_params_absolute_url,
    get_available_timezones_with_offsets,
    get_default_event_name,
    load_data_from_request,
    mask_email_address,
    relative_date_parse,
)


class TestGeneralUtils(TestCase):
    def test_mask_email_address(self):
        self.assertEqual(mask_email_address("hey@posthog.com"), "h*y@posthog.com")
        self.assertEqual(mask_email_address("richard@gmail.com"), "r*****d@gmail.com")
        self.assertEqual(
            mask_email_address("m@posthog.com"), "*@posthog.com"
        )  # one letter emails are masked differently
        self.assertEqual(mask_email_address("test+alias@posthog.com"), "t********s@posthog.com")

        with self.assertRaises(ValueError) as e:
            mask_email_address("not an email")
        self.assertEqual(str(e.exception), "Please provide a valid email address.")

    def test_available_timezones(self):
        timezones = get_available_timezones_with_offsets()
        self.assertEqual(timezones.get("Europe/Moscow"), 3)

    def test_format_query_params_absolute_url(self):
        build_req = HttpRequest()
        build_req.META = {"HTTP_HOST": "www.testserver"}

        test_to_expected: list = [
            (None, (50, None), "http://www.testserver?offset=50"),
            (None, (50, None), "http://www.testserver?offset=50"),
            (None, (None, 50), "http://www.testserver?limit=50"),
            (None, (50, 100), "http://www.testserver?offset=50&limit=100"),
            (None, (None, None), "http://www.testserver"),
            ("http://www.testserver?offset=20", (50, None), "http://www.testserver?offset=50"),
            ("http://www.testserver?limit=20", (None, 50), "http://www.testserver?limit=50"),
            ("http://www.testserver?offset=20&limit=20", (50, 50), "http://www.testserver?offset=50&limit=50"),
            # test with alias
            (None, (50, None, "off2", "lim2"), "http://www.testserver?off2=50"),
            (None, (50, None, "off2", "lim2"), "http://www.testserver?off2=50"),
            (None, (None, 50, "off2", "lim2"), "http://www.testserver?lim2=50"),
            (None, (50, 100, "off2", "lim2"), "http://www.testserver?off2=50&lim2=100"),
            (None, (None, None, "off2", "lim2"), "http://www.testserver"),
            ("http://www.testserver?off2=20", (50, None, "off2", "lim2"), "http://www.testserver?off2=50"),
            ("http://www.testserver?lim2=20", (None, 50, "off2", "lim2"), "http://www.testserver?lim2=50"),
            (
                "http://www.testserver?off2=20&lim2=20",
                (50, 50, "off2", "lim2"),
                "http://www.testserver?off2=50&lim2=50",
            ),
        ]

        for start_url, params, expected in test_to_expected:
            self.assertEqual(expected, format_query_params_absolute_url(Request(build_req, start_url), *params))


class TestRelativeDateParse(TestCase):
    @freeze_time("2020-01-31T12:22:23")
    def test_hour(self):
        self.assertEqual(relative_date_parse("-24h").isoformat(), "2020-01-30T12:00:00+00:00")
        self.assertEqual(relative_date_parse("-48h").isoformat(), "2020-01-29T12:00:00+00:00")

    @freeze_time("2020-01-31")
    def test_day(self):
        self.assertEqual(relative_date_parse("dStart").strftime("%Y-%m-%d"), "2020-01-31")
        self.assertEqual(relative_date_parse("-1d").strftime("%Y-%m-%d"), "2020-01-30")
        self.assertEqual(relative_date_parse("-2d").strftime("%Y-%m-%d"), "2020-01-29")

    @freeze_time("2020-01-31")
    def test_month(self):
        self.assertEqual(relative_date_parse("-1m").strftime("%Y-%m-%d"), "2019-12-31")
        self.assertEqual(relative_date_parse("-2m").strftime("%Y-%m-%d"), "2019-11-30")

        self.assertEqual(relative_date_parse("mStart").strftime("%Y-%m-%d"), "2020-01-01")
        self.assertEqual(relative_date_parse("-1mStart").strftime("%Y-%m-%d"), "2019-12-01")
        self.assertEqual(relative_date_parse("-2mStart").strftime("%Y-%m-%d"), "2019-11-01")

        self.assertEqual(relative_date_parse("-1mEnd").strftime("%Y-%m-%d"), "2019-12-31")
        self.assertEqual(relative_date_parse("-2mEnd").strftime("%Y-%m-%d"), "2019-11-30")

    @freeze_time("2020-01-31")
    def test_year(self):
        self.assertEqual(relative_date_parse("-1y").strftime("%Y-%m-%d"), "2019-01-31")
        self.assertEqual(relative_date_parse("-2y").strftime("%Y-%m-%d"), "2018-01-31")

        self.assertEqual(relative_date_parse("yStart").strftime("%Y-%m-%d"), "2020-01-01")
        self.assertEqual(relative_date_parse("-1yStart").strftime("%Y-%m-%d"), "2019-01-01")

    @freeze_time("2020-01-31")
    def test_normal_date(self):
        self.assertEqual(relative_date_parse("2019-12-31").strftime("%Y-%m-%d"), "2019-12-31")


class TestDefaultEventName(BaseTest):
    def test_no_events(self):
        self.assertEqual(get_default_event_name(), "$pageview")

    def test_take_screen(self):
        EventDefinition.objects.create(name="$screen", team=self.team)
        self.assertEqual(get_default_event_name(), "$screen")

    def test_prefer_pageview(self):
        EventDefinition.objects.create(name="$pageview", team=self.team)
        EventDefinition.objects.create(name="$screen", team=self.team)
        self.assertEqual(get_default_event_name(), "$pageview")


class TestLoadDataFromRequest(TestCase):
    @patch("posthog.utils.configure_scope")
    def test_pushes_request_origin_into_sentry_scope(self, patched_scope):
        origin = "potato.io"
        referer = "https://" + origin

        mock_set_tag = mock_sentry_context_for_tagging(patched_scope)

        rf = RequestFactory()
        post_request = rf.post("/s/", "content", "text/plain")
        post_request.META["REMOTE_HOST"] = origin
        post_request.META["HTTP_REFERER"] = referer

        with self.assertRaises(RequestParsingError) as ctx:
            load_data_from_request(post_request)

        patched_scope.assert_called_once()
        mock_set_tag.assert_has_calls([call("origin", origin), call("referer", referer)])

    @patch("posthog.utils.configure_scope")
    def test_pushes_request_origin_into_sentry_scope_even_when_not_available(self, patched_scope):
        mock_set_tag = mock_sentry_context_for_tagging(patched_scope)

        rf = RequestFactory()
        post_request = rf.post("/s/", "content", "text/plain")

        with self.assertRaises(RequestParsingError):
            load_data_from_request(post_request)

        patched_scope.assert_called_once()
        mock_set_tag.assert_has_calls([call("origin", "unknown"), call("referer", "unknown")])

    def test_fails_to_JSON_parse_the_literal_string_undefined_when_not_compressed(self):
        """
        load_data_from_request assumes that any data
        that has been received (and possibly decompressed) from the body
        can be parsed as JSON
        this test maintains the default (and possibly undesirable) behaviour for the uncompressed case
        """
        rf = RequestFactory()
        post_request = rf.post("/s/", "undefined", "text/plain")

        with self.assertRaises(RequestParsingError) as ctx:
            load_data_from_request(post_request)

        self.assertEqual("Invalid JSON: Expecting value: line 1 column 1 (char 0)", str(ctx.exception))

    def test_raises_specific_error_for_the_literal_string_undefined_when_compressed(self):
        rf = RequestFactory()
        post_request = rf.post("/s/?compression=gzip-js", "undefined", "text/plain")

        with self.assertRaises(RequestParsingError) as ctx:
            load_data_from_request(post_request)

        self.assertEqual(
            "data being loaded from the request body for decompression is the literal string 'undefined'",
            str(ctx.exception),
        )
