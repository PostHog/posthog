from unittest.mock import call, patch

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
    format_query_params_absolute_url,
    get_available_timezones_with_offsets,
    get_default_event_name,
    load_data_from_request,
    mask_email_address,
    relative_date_parse,
    should_refresh,
)


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
            ((50, 50, "off2", "lim2"), "http://www.testserver?off2=50&lim2=50",),
        ]

        for params, expected in test_to_expected:
            self.assertEqual(expected, format_query_params_absolute_url(Request(request=build_req), *params))

    def test_format_query_params_absolute_url_with_https(self) -> None:
        with self.settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")):
            build_req = HttpRequest()
            build_req.META = {"HTTP_HOST": "www.testserver", "HTTP_X_FORWARDED_PROTO": "https"}
            request: Request = Request(build_req)
            self.assertEqual("https://www.testserver", format_query_params_absolute_url(request))


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

    @patch("os.getenv")
    def test_fetching_env_var_parsed_as_int(self, mock_env):
        mock_env.return_value = ""
        self.assertEqual(get_from_env("test_key", optional=True, type_cast=int), None)

        mock_env.return_value = "4"
        self.assertEqual(get_from_env("test_key", type_cast=int), 4)


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
            [call("origin", origin), call("referer", referer), call("library.version", "1.20.0")]
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
            [call("origin", origin), call("referer", referer), call("library.version", "1.20.0")]
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
            [call("origin", "unknown"), call("referer", "unknown"), call("library.version", "unknown")]
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
    def test_should_refresh_with_refresh_true(self):
        request = HttpRequest()
        request.GET["refresh"] = "true"
        self.assertTrue(should_refresh(Request(request)))

    def test_should_refresh_with_refresh_empty(self):
        request = HttpRequest()
        request.GET["refresh"] = ""
        self.assertTrue(should_refresh(Request(request)))

    def test_should_not_refresh_with_refresh_false(self):
        request = HttpRequest()
        request.GET["refresh"] = "false"
        self.assertFalse(should_refresh(Request(request)))

    def test_should_not_refresh_with_refresh_gibberish(self):
        request = HttpRequest()
        request.GET["refresh"] = "2132klkl"
        self.assertFalse(should_refresh(Request(request)))

    def test_should_refresh_with_data_true(self):
        drf_request = Request(HttpRequest())
        drf_request._full_data = {"refresh": True}  # type: ignore
        self.assertTrue(should_refresh((drf_request)))

    def test_should_not_refresh_with_data_false(self):
        drf_request = Request(HttpRequest())
        drf_request._full_data = {"refresh": False}  # type: ignore
        self.assertFalse(should_refresh(drf_request))
