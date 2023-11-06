from datetime import datetime
from unittest.mock import call, patch
from zoneinfo import ZoneInfo

import pytest
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpRequest
from django.test import TestCase
from django.test.client import RequestFactory
from freezegun import freeze_time
from rest_framework.request import Request

from posthog.api.test.mock_sentry import mock_sentry_context_for_tagging
from posthog.exceptions import RequestParsingError
from posthog.models import EventDefinition
from posthog.settings.utils import get_from_env
from posthog.test.base import BaseTest
from posthog.utils import (
    PotentialSecurityProblemException,
    absolute_uri,
    flatten,
    format_query_params_absolute_url,
    get_available_timezones_with_offsets,
    get_compare_period_dates,
    get_default_event_name,
    load_data_from_request,
    refresh_requested_by_client,
    relative_date_parse,
)


class TestAbsoluteUrls(TestCase):
    def test_format_absolute_url(self) -> None:
        regression_11204 = "api/projects/6642/insights/trend/?events=%5B%7B%22id%22%3A%22product%20viewed%22%2C%22name%22%3A%22product%20viewed%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%5D&actions=%5B%5D&display=ActionsTable&insight=TRENDS&interval=day&breakdown=productName&new_entity=%5B%5D&properties=%5B%5D&step_limit=5&funnel_filter=%7B%7D&breakdown_type=event&exclude_events=%5B%5D&path_groupings=%5B%5D&include_event_types=%5B%22%24pageview%22%5D&filter_test_accounts=false&local_path_cleaning_filters=%5B%5D&date_from=-14d&offset=50"
        absolute_urls_test_cases = [
            (None, "https://my-amazing.site", "https://my-amazing.site"),
            (None, "https://my-amazing.site/", "https://my-amazing.site/"),
            (
                "api/path",
                "https://my-amazing.site/",
                "https://my-amazing.site/api/path",
            ),
            (
                "/api/path",
                "https://my-amazing.site/",
                "https://my-amazing.site/api/path",
            ),
            (
                "api/path",
                "https://my-amazing.site/base_url/",
                "https://my-amazing.site/base_url/api/path",
            ),
            (
                "/api/path",
                "https://my-amazing.site/base_url",
                "https://my-amazing.site/base_url/api/path",
            ),
            (
                regression_11204,
                "https://app.posthog.com",
                f"https://app.posthog.com/{regression_11204}",
            ),
            (
                "https://app.posthog.com",
                "https://app.posthog.com",
                "https://app.posthog.com",
            ),
            (
                "https://app.posthog.com/some/path?=something",
                "https://app.posthog.com",
                "https://app.posthog.com/some/path?=something",
            ),
            (
                "an.external.domain.com/something-outside-posthog",
                "https://app.posthog.com",
                "https://app.posthog.com/an.external.domain.com/something-outside-posthog",
            ),
            ("/api/path", "", "/api/path"),  # current behavior whether correct or not
            (
                "/api/path",
                "some-internal-dns-value",
                "some-internal-dns-value/api/path",
            ),  # current behavior whether correct or not
        ]
        for url, site_url, expected in absolute_urls_test_cases:
            with self.subTest():
                with self.settings(SITE_URL=site_url):
                    self.assertEqual(
                        expected,
                        absolute_uri(url),
                        msg=f"with URL='{url}' & site_url setting='{site_url}' actual did not equal {expected}",
                    )

    def test_absolute_uri_can_not_escape_out_host(self) -> None:
        with self.settings(SITE_URL="https://app.posthog.com"):
            with pytest.raises(PotentialSecurityProblemException):
                (absolute_uri("https://an.external.domain.com/something-outside-posthog"),)

    def test_absolute_uri_can_not_escape_out_host_on_different_scheme(self) -> None:
        with self.settings(SITE_URL="https://app.posthog.com"):
            with pytest.raises(PotentialSecurityProblemException):
                (absolute_uri("ftp://an.external.domain.com/something-outside-posthog"),)

    def test_absolute_uri_can_not_escape_out_host_when_site_url_is_the_empty_string(self) -> None:
        with self.settings(SITE_URL=""):
            with pytest.raises(PotentialSecurityProblemException):
                (absolute_uri("https://an.external.domain.com/something-outside-posthog"),)


class TestFormatUrls(TestCase):
    factory = RequestFactory()

    def test_format_query_params_absolute_url(self) -> None:
        build_req = HttpRequest()
        build_req.META = {"HTTP_HOST": "www.testserver"}

        test_to_expected: list = [
            ((50, None), "http://www.testserver?offset=50"),
            ((50, None), "http://www.testserver?offset=50"),
            ((None, 50), "http://www.testserver?limit=50"),
            ((50, 100), "http://www.testserver?offset=50&limit=100"),
            ((None, None), "http://www.testserver"),
            ((50, None), "http://www.testserver?offset=50"),
            ((None, 50), "http://www.testserver?limit=50"),
            ((50, 50), "http://www.testserver?offset=50&limit=50"),
            # test with alias
            ((50, None, "off2", "lim2"), "http://www.testserver?off2=50"),
            ((50, None, "off2", "lim2"), "http://www.testserver?off2=50"),
            ((None, 50, "off2", "lim2"), "http://www.testserver?lim2=50"),
            ((50, 100, "off2", "lim2"), "http://www.testserver?off2=50&lim2=100"),
            ((None, None, "off2", "lim2"), "http://www.testserver"),
            ((50, None, "off2", "lim2"), "http://www.testserver?off2=50"),
            ((None, 50, "off2", "lim2"), "http://www.testserver?lim2=50"),
            ((50, 50, "off2", "lim2"), "http://www.testserver?off2=50&lim2=50"),
        ]

        for params, expected in test_to_expected:
            self.assertEqual(
                expected,
                format_query_params_absolute_url(Request(request=build_req), *params),
            )

    def test_format_query_params_absolute_url_with_https(self) -> None:
        with self.settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")):
            build_req = HttpRequest()
            build_req.META = {
                "HTTP_HOST": "www.testserver",
                "HTTP_X_FORWARDED_PROTO": "https",
            }
            request: Request = Request(build_req)
            self.assertEqual("https://www.testserver", format_query_params_absolute_url(request))


class TestGeneralUtils(TestCase):
    def test_available_timezones(self):
        timezones = get_available_timezones_with_offsets()
        self.assertEqual(timezones.get("Europe/Moscow"), 3)

    @patch("os.getenv")
    def test_fetching_env_var_parsed_as_int(self, mock_env):
        mock_env.return_value = ""
        self.assertEqual(get_from_env("test_key", optional=True, type_cast=int), None)

        mock_env.return_value = "4"
        self.assertEqual(get_from_env("test_key", type_cast=int), 4)

    @patch("os.getenv")
    def test_fetching_env_var_parsed_as_float(self, mock_env):
        mock_env.return_value = ""
        self.assertEqual(get_from_env("test_key", optional=True, type_cast=float, default=0.0), None)

        mock_env.return_value = ""
        self.assertEqual(get_from_env("test_key", type_cast=float, default=0.0), 0.0)

        mock_env.return_value = "4"
        self.assertEqual(get_from_env("test_key", type_cast=float), 4.0)

    @patch("os.getenv")
    def test_fetching_env_var_parsed_as_float_from_nonsense_input(self, mock_env):
        with pytest.raises(ValueError):
            mock_env.return_value = "wat"
            get_from_env("test_key", type_cast=float)


class TestRelativeDateParse(TestCase):
    @freeze_time("2020-01-31T12:22:23")
    def test_hour(self):
        self.assertEqual(
            relative_date_parse("-24h", ZoneInfo("UTC")).isoformat(),
            "2020-01-30T12:22:23+00:00",
        )
        self.assertEqual(
            relative_date_parse("-48h", ZoneInfo("UTC")).isoformat(),
            "2020-01-29T12:22:23+00:00",
        )

    @freeze_time("2020-01-31")
    def test_day(self):
        self.assertEqual(
            relative_date_parse("dStart", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2020-01-31",
        )
        self.assertEqual(
            relative_date_parse("-1d", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2020-01-30",
        )
        self.assertEqual(
            relative_date_parse("-2d", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2020-01-29",
        )

        self.assertEqual(
            relative_date_parse("-1dStart", ZoneInfo("UTC")).isoformat(),
            "2020-01-30T00:00:00+00:00",
        )
        self.assertEqual(
            relative_date_parse("-1dEnd", ZoneInfo("UTC")).isoformat(),
            "2020-01-30T23:59:59.999999+00:00",
        )

    @freeze_time("2020-01-31")
    def test_month(self):
        self.assertEqual(
            relative_date_parse("-1m", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2019-12-31",
        )
        self.assertEqual(
            relative_date_parse("-2m", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2019-11-30",
        )

        self.assertEqual(
            relative_date_parse("mStart", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2020-01-01",
        )
        self.assertEqual(
            relative_date_parse("-1mStart", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2019-12-01",
        )
        self.assertEqual(
            relative_date_parse("-2mStart", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2019-11-01",
        )

        self.assertEqual(
            relative_date_parse("-1mEnd", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2019-12-31",
        )
        self.assertEqual(
            relative_date_parse("-2mEnd", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2019-11-30",
        )

    @freeze_time("2020-01-31")
    def test_year(self):
        self.assertEqual(
            relative_date_parse("-1y", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2019-01-31",
        )
        self.assertEqual(
            relative_date_parse("-2y", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2018-01-31",
        )

        self.assertEqual(
            relative_date_parse("yStart", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2020-01-01",
        )
        self.assertEqual(
            relative_date_parse("-1yStart", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2019-01-01",
        )

    @freeze_time("2020-01-31")
    def test_normal_date(self):
        self.assertEqual(
            relative_date_parse("2019-12-31", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2019-12-31",
        )


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
    def _create_request_with_headers(self, origin: str, referer: str) -> WSGIRequest:
        rf = RequestFactory()
        # the server presents any http headers in upper case with http_ as a prefix
        # see https://docs.djangoproject.com/en/4.0/ref/request-response/#django.http.HttpRequest.META
        headers = {"HTTP_ORIGIN": origin, "HTTP_REFERER": referer}
        post_request = rf.post("/e/?ver=1.20.0", "content", "text/plain", False, **headers)
        return post_request

    @patch("posthog.utils.configure_scope")
    def test_pushes_debug_information_into_sentry_scope_from_origin_header(self, patched_scope):
        origin = "potato.io"
        referer = "https://" + origin

        mock_set_tag = mock_sentry_context_for_tagging(patched_scope)

        post_request = self._create_request_with_headers(origin, referer)

        with self.assertRaises(RequestParsingError):
            load_data_from_request(post_request)

        patched_scope.assert_called_once()
        mock_set_tag.assert_has_calls(
            [
                call("origin", origin),
                call("referer", referer),
                call("library.version", "1.20.0"),
            ]
        )

    @patch("posthog.utils.configure_scope")
    def test_pushes_debug_information_into_sentry_scope_when_origin_header_not_present(self, patched_scope):
        origin = "potato.io"
        referer = "https://" + origin

        mock_set_tag = mock_sentry_context_for_tagging(patched_scope)

        post_request = self._create_request_with_headers(origin, referer)

        with self.assertRaises(RequestParsingError):
            load_data_from_request(post_request)

        patched_scope.assert_called_once()
        mock_set_tag.assert_has_calls(
            [
                call("origin", origin),
                call("referer", referer),
                call("library.version", "1.20.0"),
            ]
        )

    @patch("posthog.utils.configure_scope")
    def test_still_tags_sentry_scope_even_when_debug_signal_is_not_available(self, patched_scope):
        mock_set_tag = mock_sentry_context_for_tagging(patched_scope)

        rf = RequestFactory()
        post_request = rf.post("/s/", "content", "text/plain")

        with self.assertRaises(RequestParsingError):
            load_data_from_request(post_request)

        patched_scope.assert_called_once()
        mock_set_tag.assert_has_calls(
            [
                call("origin", "unknown"),
                call("referer", "unknown"),
                call("library.version", "unknown"),
            ]
        )

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

        self.assertEqual(
            "Invalid JSON: Expecting value: line 1 column 1 (char 0)",
            str(ctx.exception),
        )

    def test_raises_specific_error_for_the_literal_string_undefined_when_compressed(self):
        rf = RequestFactory()
        post_request = rf.post("/s/?compression=gzip-js", "undefined", "text/plain")

        with self.assertRaises(RequestParsingError) as ctx:
            load_data_from_request(post_request)

        self.assertEqual(
            "data being loaded from the request body for decompression is the literal string 'undefined'",
            str(ctx.exception),
        )

    @patch("posthog.utils.gzip")
    def test_can_decompress_gzipped_body_received_with_no_compression_flag(self, patched_gzip):
        # see https://sentry.io/organizations/posthog2/issues/3136510367
        # one organization is causing a request parsing error by sending an encoded body
        # but the empty string for the compression value
        # this accounts for a large majority of our Sentry errors

        patched_gzip.decompress.return_value = '{"what is it": "the decompressed value"}'

        rf = RequestFactory()
        # a request with no compression set
        post_request = rf.post("/s/", "the gzip compressed string", "text/plain")

        data = load_data_from_request(post_request)
        self.assertEqual({"what is it": "the decompressed value"}, data)


class TestShouldRefresh(TestCase):
    def test_refresh_requested_by_client_with_refresh_true(self):
        request = HttpRequest()
        request.GET["refresh"] = "true"
        self.assertTrue(refresh_requested_by_client(Request(request)))

    def test_refresh_requested_by_client_with_refresh_empty(self):
        request = HttpRequest()
        request.GET["refresh"] = ""
        self.assertTrue(refresh_requested_by_client(Request(request)))

    def test_should_not_refresh_with_refresh_false(self):
        request = HttpRequest()
        request.GET["refresh"] = "false"
        self.assertFalse(refresh_requested_by_client(Request(request)))

    def test_should_not_refresh_with_refresh_gibberish(self):
        request = HttpRequest()
        request.GET["refresh"] = "2132klkl"
        self.assertFalse(refresh_requested_by_client(Request(request)))

    def test_refresh_requested_by_client_with_data_true(self):
        drf_request = Request(HttpRequest())
        drf_request._full_data = {"refresh": True}  # type: ignore
        self.assertTrue(refresh_requested_by_client((drf_request)))

    def test_should_not_refresh_with_data_false(self):
        drf_request = Request(HttpRequest())
        drf_request._full_data = {"refresh": False}  # type: ignore
        self.assertFalse(refresh_requested_by_client(drf_request))

    def test_can_get_period_to_compare_when_interval_is_day(self) -> None:
        """
        regression test see https://sentry.io/organizations/posthog/issues/3719740579/events/latest/?project=1899813&referrer=latest-event
        """
        assert get_compare_period_dates(
            date_from=datetime(2022, 1, 1, 0, 0),
            date_to=datetime(2022, 11, 4, 21, 20, 41, 730028),
            date_from_delta_mapping={"day": 1, "month": 1},
            date_to_delta_mapping=None,
            interval="day",
        ) == (datetime(2021, 2, 27, 0, 0), datetime(2021, 12, 31, 23, 59, 59, 999999))


class TestFlatten(TestCase):
    def test_flatten_lots_of_depth(self):
        assert list(flatten([1, [2, 3], [[4], [5, [6, 7]]]])) == [1, 2, 3, 4, 5, 6, 7]

    def test_flatten_single_depth(self):
        assert list(flatten([1, [2, 3], [[4], [5, [6, 7]]]], max_depth=1)) == [
            1,
            2,
            3,
            [4],
            [5, [6, 7]],
        ]
