import os
import json
import base64
import tempfile
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import call, patch

from django.core.cache import cache
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpRequest
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.client import RequestFactory
from django.utils.timezone import now

from parameterized import parameterized
from rest_framework.request import Request

from posthog.exceptions import RequestParsingError, UnspecifiedCompressionFallbackParsingError
from posthog.models import EventDefinition, Organization, PropertyDefinition, Team, User
from posthog.settings.utils import get_from_env

if TYPE_CHECKING:
    from posthog.models.group_type_mapping import GroupTypeMapping

from posthog.utils import (
    HAS_PERSON_EMAIL_ABSENT_TTL_SECONDS,
    HAS_PERSON_EMAIL_ABSENT_YOUNG_PROJECT_TTL_SECONDS,
    HAS_PERSON_EMAIL_PRESENT_TTL_SECONDS,
    PotentialSecurityProblemException,
    _build_flag_provider,
    _read_preload_manifest,
    absolute_uri,
    base64_decode,
    filters_override_requested_by_client,
    flatten,
    format_query_params_absolute_url,
    get_available_timezones_with_offsets,
    get_compare_period_dates,
    get_default_event_info,
    get_default_event_name,
    get_dogfood_flags_team_id,
    get_has_person_email,
    get_ip_address,
    get_js_url,
    get_self_capture_team_id,
    get_short_user_agent,
    load_data_from_request,
    refresh_requested_by_client,
    relative_date_parse,
    resolve_dogfood_flags_team,
    resolve_self_capture_team,
    str_to_int_set,
    tile_filters_override_requested_by_client,
    variables_override_requested_by_client,
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

    @parameterized.expand(
        [
            # `urlparse` returns hostname='app.posthog.com' so the SITE_URL host check
            # passes, but HTTP clients/browsers route to attacker.example.
            ("raw_backslash", "https://attacker.example\\@app.posthog.com/path"),
            ("percent_encoded_backslash", "https://attacker.example%5C@app.posthog.com/path"),
        ]
    )
    def test_absolute_uri_rejects_backslash_authority_bypass(self, _name: str, url: str) -> None:
        with self.settings(SITE_URL="https://app.posthog.com"):
            with pytest.raises(PotentialSecurityProblemException):
                absolute_uri(url)


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
            request: Request = Request(build_req)  # ty: ignore[invalid-assignment]
            self.assertEqual("https://www.testserver", format_query_params_absolute_url(request))


class TestGetJsUrl(TestCase):
    factory = RequestFactory()

    @parameterized.expand(
        [
            (
                "http_rewrites_host",
                True,
                "http://localhost:8234",
                "dev-container:8000",
                False,
                "http://dev-container:8234",
            ),
            (
                "https_keeps_localhost",
                True,
                "http://localhost:8234",
                "my-tunnel.ngrok-free.dev",
                True,
                "http://localhost:8234",
            ),
            (
                "non_localhost_unchanged",
                True,
                "https://cdn.example.com/static",
                "dev-container:8000",
                False,
                "https://cdn.example.com/static",
            ),
            (
                "non_debug_unchanged",
                False,
                "http://localhost:8234",
                "dev-container:8000",
                False,
                "http://localhost:8234",
            ),
            (
                "http_rewrites_ipv6_host",
                True,
                "http://localhost:8234",
                "[::1]:8000",
                False,
                "http://[::1]:8234",
            ),
            (
                "http_rewrites_host_without_port",
                True,
                "http://localhost:8234",
                "dev-container",
                False,
                "http://dev-container:8234",
            ),
        ]
    )
    def test_get_js_url(
        self, _name: str, debug: bool, js_url: str, http_host: str, is_https: bool, expected: str
    ) -> None:
        settings_kwargs: dict = {"DEBUG": debug, "JS_URL": js_url}
        if is_https:
            settings_kwargs["SECURE_PROXY_SSL_HEADER"] = ("HTTP_X_FORWARDED_PROTO", "https")
        with self.settings(**settings_kwargs):
            if is_https:
                request = self.factory.get("/", HTTP_HOST=http_host, HTTP_X_FORWARDED_PROTO="https")
            else:
                request = self.factory.get("/", HTTP_HOST=http_host)
            self.assertEqual(expected, get_js_url(request))


class TestGeneralUtils(TestCase):
    def test_available_timezones(self):
        timezones = get_available_timezones_with_offsets()
        self.assertEqual(timezones.get("Europe/Moscow"), 3)

    def test_available_timezones_buckets_by_hour(self):
        from posthog.utils import _timezone_offsets_for_hour

        _timezone_offsets_for_hour.cache_clear()

        with patch("posthog.utils.dt") as mock_dt:
            mock_dt.datetime.now.return_value = datetime(2026, 5, 3, 10, 30)
            mock_dt.datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
            mock_dt.timedelta = timedelta

            first = get_available_timezones_with_offsets()
            second = get_available_timezones_with_offsets()
            assert first is second  # same hour -> single inner-cache entry

            mock_dt.datetime.now.return_value = datetime(2026, 5, 3, 11, 0)
            third = get_available_timezones_with_offsets()
            assert third is not first  # crossed an hour boundary -> recomputed

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

    @parameterized.expand(
        [
            ("minus_one", "-1q", "2019-10-31"),
            ("minus_two", "-2q", "2019-07-31"),
            ("current_start", "qStart", "2020-01-01"),
            ("current_end", "qEnd", "2020-03-31"),
            ("minus_one_start", "-1qStart", "2019-10-01"),
            ("minus_two_start", "-2qStart", "2019-07-01"),
            ("minus_one_end", "-1qEnd", "2019-12-31"),
            ("minus_two_end", "-2qEnd", "2019-09-30"),
        ]
    )
    @freeze_time("2020-01-31")
    def test_quarter(self, _name, input, expected_date):
        self.assertEqual(
            relative_date_parse(input, ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            expected_date,
        )

    @freeze_time("2020-01-31")
    def test_quarter_human_friendly_comparison_periods_keeps_week_alignment(self):
        self.assertEqual(
            relative_date_parse("-1q", ZoneInfo("UTC"), human_friendly_comparison_periods=True).strftime("%Y-%m-%d"),
            "2019-11-01",
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

    @parameterized.expand(
        [
            # 2020-01-31 is a Friday
            # Sunday week start (default): week started on Sunday Jan 26
            ("sunday_start", 0, "2020-01-26"),
            # Monday week start: week started on Monday Jan 27
            ("monday_start", 1, "2020-01-27"),
        ]
    )
    @freeze_time("2020-01-31")
    def test_week_start(self, _name, week_start_day, expected_date):
        self.assertEqual(
            relative_date_parse("wStart", ZoneInfo("UTC"), team_week_start_day=week_start_day).strftime("%Y-%m-%d"),
            expected_date,
        )

    @freeze_time("2020-01-31")
    def test_normal_date(self):
        self.assertEqual(
            relative_date_parse("2019-12-31", ZoneInfo("UTC")).strftime("%Y-%m-%d"),
            "2019-12-31",
        )


class TestDefaultEventName(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_no_events_returns_pageview_default(self):
        # When team has no events at all, default to $pageview (most common for new teams)
        self.assertEqual(get_default_event_name(self.team), "$pageview")

    def test_other_events_but_no_pageview_or_screen_returns_none(self):
        # When team has events but no $pageview or $screen, return None for "all events"
        EventDefinition.objects.create(name="custom_event", team=self.team)
        self.assertIsNone(get_default_event_name(self.team))

    def test_take_screen(self):
        EventDefinition.objects.create(name="$screen", team=self.team)
        self.assertEqual(get_default_event_name(self.team), "$screen")

    @parameterized.expand(
        [
            (
                "no_events",
                False,
                False,
                {"default_event_name": "$pageview", "has_pageview": False, "has_screen": False},
            ),
            ("only_screen", False, True, {"default_event_name": "$screen", "has_pageview": False, "has_screen": True}),
            (
                "only_pageview",
                True,
                False,
                {"default_event_name": "$pageview", "has_pageview": True, "has_screen": False},
            ),
            ("both", True, True, {"default_event_name": "$pageview", "has_pageview": True, "has_screen": True}),
        ]
    )
    def test_get_default_event_info(self, _name, create_pageview, create_screen, expected):
        if create_pageview:
            EventDefinition.objects.create(name="$pageview", team=self.team)
        if create_screen:
            EventDefinition.objects.create(name="$screen", team=self.team)
        self.assertEqual(get_default_event_info(self.team), expected)

    @parameterized.expand(
        [
            ("no_events", False, False, "$pageview"),
            ("only_screen", False, True, "$screen"),
            ("only_pageview", True, False, "$pageview"),
            ("both", True, True, "$pageview"),
        ]
    )
    def test_get_default_event_name(self, _name, create_pageview, create_screen, expected):
        if create_pageview:
            EventDefinition.objects.create(name="$pageview", team=self.team)
        if create_screen:
            EventDefinition.objects.create(name="$screen", team=self.team)
        self.assertEqual(get_default_event_name(self.team), expected)

    def test_negative_result_is_not_cached(self):
        # Empty teams may simply not have ingested events yet — caching the
        # negative would block them from ever updating to the positive answer.
        with self.assertNumQueries(2):
            get_default_event_info(self.team)
        with self.assertNumQueries(2):
            get_default_event_info(self.team)

    def test_positive_result_is_cached(self):
        EventDefinition.objects.create(name="$pageview", team=self.team)
        with self.assertNumQueries(1):
            get_default_event_info(self.team)
        with self.assertNumQueries(0):
            get_default_event_info(self.team)

    @parameterized.expand(
        [
            ("only_pageview", True, False, 30 * 60),
            ("only_screen", False, True, 30 * 60),
            ("both", True, True, 24 * 60 * 60),
        ]
    )
    def test_cache_ttl_depends_on_completeness(
        self, _name: str, create_pageview: bool, create_screen: bool, expected_ttl: int
    ):
        from posthog.utils import _default_event_info_cache_key

        if create_pageview:
            EventDefinition.objects.create(name="$pageview", team=self.team)
        if create_screen:
            EventDefinition.objects.create(name="$screen", team=self.team)

        with patch("posthog.utils.safe_cache_set") as mock_set:
            get_default_event_info(self.team)

        mock_set.assert_called_once()
        args, kwargs = mock_set.call_args
        assert args[0] == _default_event_info_cache_key(self.team.id)
        assert kwargs["timeout"] == expected_ttl

    def test_cache_invalidated_when_default_event_definition_deleted(self):
        ed = EventDefinition.objects.create(name="$pageview", team=self.team)
        # warm the cache
        assert get_default_event_info(self.team)["has_pageview"] is True
        with self.assertNumQueries(0):
            assert get_default_event_info(self.team)["has_pageview"] is True

        ed.delete()
        # cache should now be cold and reflect the new ground truth
        assert get_default_event_info(self.team)["has_pageview"] is False

    def test_cache_invalidated_when_default_event_definition_renamed_away(self):
        ed = EventDefinition.objects.create(name="$pageview", team=self.team)
        assert get_default_event_info(self.team)["has_pageview"] is True

        ed.name = "pageview_legacy"
        ed.save()
        # rename of the cached default event must bust the cache
        assert get_default_event_info(self.team)["has_pageview"] is False

    def test_cache_invalidated_when_default_event_definition_renamed_in(self):
        ed = EventDefinition.objects.create(name="legacy_event", team=self.team)
        assert get_default_event_info(self.team)["has_pageview"] is False

        ed.name = "$pageview"
        ed.save()
        # renaming an event into one of the defaults must bust the cache
        assert get_default_event_info(self.team)["has_pageview"] is True

    def test_cache_not_invalidated_when_unrelated_event_definition_changed(self):
        EventDefinition.objects.create(name="$pageview", team=self.team)
        EventDefinition.objects.create(name="$screen", team=self.team)
        # warm the both-present cache
        assert get_default_event_info(self.team) == {
            "default_event_name": "$pageview",
            "has_pageview": True,
            "has_screen": True,
        }

        # creating an unrelated event definition should NOT bust the cache
        EventDefinition.objects.create(name="custom_event", team=self.team)
        with self.assertNumQueries(0):
            get_default_event_info(self.team)

    @parameterized.expand(
        [
            ("person_email_present", "email", PropertyDefinition.Type.PERSON, True),
            ("dollar_email_ignored", "$email", PropertyDefinition.Type.PERSON, False),
            ("event_email_ignored", "email", PropertyDefinition.Type.EVENT, False),
            ("other_person_property_ignored", "name", PropertyDefinition.Type.PERSON, False),
        ]
    )
    def test_get_has_person_email(self, _name, prop_name, prop_type, expected):
        PropertyDefinition.objects.create(name=prop_name, type=prop_type, team=self.team)
        assert get_has_person_email(self.team) is expected

    def test_has_person_email_is_project_scoped_not_team_scoped(self):
        other_team = Team.objects.create(organization=self.organization, project=self.team.project)
        PropertyDefinition.objects.create(
            name="email", type=PropertyDefinition.Type.PERSON, team=other_team, project=self.team.project
        )
        assert get_has_person_email(self.team) is True

    @parameterized.expand(
        [
            ("present_young_project", True, 0, HAS_PERSON_EMAIL_PRESENT_TTL_SECONDS),
            ("present_old_project", True, 30, HAS_PERSON_EMAIL_PRESENT_TTL_SECONDS),
            ("absent_young_project", False, 0, HAS_PERSON_EMAIL_ABSENT_YOUNG_PROJECT_TTL_SECONDS),
            ("absent_old_project", False, 30, HAS_PERSON_EMAIL_ABSENT_TTL_SECONDS),
        ]
    )
    def test_has_person_email_cache_ttl_depends_on_presence_and_project_age(
        self, _name, create_email, project_age_days, expected_ttl
    ):
        if create_email:
            PropertyDefinition.objects.create(name="email", type=PropertyDefinition.Type.PERSON, team=self.team)
        self.team.project.created_at = now() - timedelta(days=project_age_days)
        self.team.project.save()
        with patch("posthog.utils.safe_cache_set") as mock_set:
            get_has_person_email(self.team)
        mock_set.assert_called_once()
        _, kwargs = mock_set.call_args
        assert kwargs["timeout"] == expected_ttl

    @parameterized.expand([("present", True), ("absent", False)])
    def test_has_person_email_result_is_cached(self, _name, create_email):
        if create_email:
            PropertyDefinition.objects.create(name="email", type=PropertyDefinition.Type.PERSON, team=self.team)
        assert self.team.project is not None
        with self.assertNumQueries(1):
            assert get_has_person_email(self.team) is create_email
        with self.assertNumQueries(0):
            assert get_has_person_email(self.team) is create_email

    def test_has_person_email_cache_invalidated_when_email_property_created(self):
        assert get_has_person_email(self.team) is False
        with self.assertNumQueries(0):
            assert get_has_person_email(self.team) is False

        with self.captureOnCommitCallbacks(execute=True):
            PropertyDefinition.objects.create(name="email", type=PropertyDefinition.Type.PERSON, team=self.team)
        assert get_has_person_email(self.team) is True

    def test_delete_does_not_invalidate_so_cascade_fast_delete_stays_enabled(self):
        pd = PropertyDefinition.objects.create(name="email", type=PropertyDefinition.Type.PERSON, team=self.team)
        assert get_has_person_email(self.team) is True

        with self.captureOnCommitCallbacks(execute=True):
            pd.delete()
        with self.assertNumQueries(0):
            assert get_has_person_email(self.team) is True

    def test_has_person_email_cache_not_invalidated_when_unrelated_property_created(self):
        PropertyDefinition.objects.create(name="email", type=PropertyDefinition.Type.PERSON, team=self.team)
        assert get_has_person_email(self.team) is True

        with self.captureOnCommitCallbacks(execute=True):
            PropertyDefinition.objects.create(name="plan", type=PropertyDefinition.Type.PERSON, team=self.team)
        with self.assertNumQueries(0):
            assert get_has_person_email(self.team) is True


class TestLoadDataFromRequest(TestCase):
    def _create_request_with_headers(self, origin: str, referer: str) -> WSGIRequest:
        rf = RequestFactory()
        # the server presents any http headers in upper case with http_ as a prefix
        # see https://docs.djangoproject.com/en/4.0/ref/request-response/#django.http.HttpRequest.META
        post_request = rf.post(
            "/e/?ver=1.20.0",
            data="content",
            content_type="text/plain",
            secure=False,
            HTTP_ORIGIN=origin,
            HTTP_REFERER=referer,
        )
        return post_request

    @patch("posthoganalytics.tag")
    @patch("posthoganalytics.new_context")
    def test_pushes_debug_information_into_context_from_origin_header(self, patched_context, patched_tag):
        origin = "potato.io"
        referer = "https://" + origin

        post_request = self._create_request_with_headers(origin, referer)

        with self.assertRaises(UnspecifiedCompressionFallbackParsingError):
            load_data_from_request(post_request)

        patched_context.assert_called_once()
        patched_tag.assert_has_calls(
            [
                call("origin", origin),
                call("referer", referer),
                call("library.version", "1.20.0"),
            ]
        )

    @patch("posthoganalytics.tag")
    @patch("posthoganalytics.new_context")
    def test_pushes_debug_information_into_context_when_origin_header_not_present(self, patched_context, patched_tag):
        origin = "potato.io"
        referer = "https://" + origin

        post_request = self._create_request_with_headers(origin, referer)

        with self.assertRaises(UnspecifiedCompressionFallbackParsingError):
            load_data_from_request(post_request)

        patched_context.assert_called_once()
        patched_tag.assert_has_calls(
            [
                call("origin", origin),
                call("referer", referer),
                call("library.version", "1.20.0"),
            ]
        )

    @patch("posthoganalytics.tag")
    @patch("posthoganalytics.new_context")
    def test_still_tags_context_even_when_debug_signal_is_not_available(self, patched_context, patched_tag):
        rf = RequestFactory()
        post_request = rf.post("/s/", "content", "text/plain")

        with self.assertRaises(UnspecifiedCompressionFallbackParsingError):
            load_data_from_request(post_request)

        patched_context.assert_called_once()
        patched_tag.assert_has_calls(
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

        with self.assertRaises(UnspecifiedCompressionFallbackParsingError) as ctx:
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
        # one organization is causing a request parsing error by sending an encoded body
        # but the empty string for the compression value
        # this accounts for a large majority of our error tracking errors

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
        self.assertTrue(refresh_requested_by_client(drf_request))

    def test_should_not_refresh_with_data_false(self):
        drf_request = Request(HttpRequest())
        drf_request._full_data = {"refresh": False}  # type: ignore
        self.assertFalse(refresh_requested_by_client(drf_request))

    def test_should_refresh_with_data_async(self):
        drf_request = Request(HttpRequest())
        drf_request._full_data = {"refresh": "async"}  # type: ignore
        assert refresh_requested_by_client(drf_request) == "async"

    def test_can_get_period_to_compare_when_interval_is_day(self) -> None:
        assert get_compare_period_dates(
            date_from=datetime(2022, 1, 1, 0, 0),
            date_to=datetime(2022, 11, 4, 21, 20, 41, 730028),
            date_from_delta_mapping={"day": 1, "month": 1},
            date_to_delta_mapping=None,
            interval="day",
        ) == (datetime(2021, 2, 27, 0, 0), datetime(2021, 12, 31, 21, 20, 41, 730028))


class TestUtilities(TestCase):
    def test_base64_decode(self):
        # Test with a simple string
        simple_string = "Hello, World!"
        encoded = base64.b64encode(simple_string.encode("utf-8")).decode("ascii")
        self.assertEqual(base64_decode(encoded), simple_string)

        # Test with bytes input
        bytes_input = b"SGVsbG8sIFdvcmxkIQ=="
        self.assertEqual(base64_decode(bytes_input), simple_string)

        # Test with Unicode characters
        unicode_string = "こんにちは、世界！"
        unicode_encoded = base64.b64encode(unicode_string.encode("utf-8")).decode("ascii")
        self.assertEqual(base64_decode(unicode_encoded), unicode_string)

        # Test with emojis
        emoji_string = "Hello 👋 World 🌍!"
        emoji_encoded = base64.b64encode(emoji_string.encode("utf-8")).decode("ascii")
        self.assertEqual(base64_decode(emoji_encoded), emoji_string)

        # Test with padding characters removed
        no_padding = "SGVsbG8sIFdvcmxkIQ"
        self.assertEqual(base64_decode(no_padding), simple_string)

        # Tests with real URL encoded data
        encoded_data = b"data=eyJ0b2tlbiI6InBoY19HNEFGZkNtRWJXSXZXS05GWlVLaWhpNXRIaGNJU1FYd2xVYXpLMm5MdkE0IiwiZGlzdGluY3RfaWQiOiIwMTkxMmJjMS1iY2ZkLTcwNDYtOTQ0My0wNjVjZjhjYzUyYzUiLCJncm91cHMiOnt9fQ%3D%3D"
        decoded = base64_decode(encoded_data)
        decoded_json = json.loads(decoded)

        self.assertEqual(decoded_json["token"], "phc_G4AFfCmEbWIvWKNFZUKihi5tHhcISQXwlUazK2nLvA4")
        self.assertEqual(decoded_json["distinct_id"], "01912bc1-bcfd-7046-9443-065cf8cc52c5")
        self.assertEqual(decoded_json["groups"], {})

        encoded_data = b"eyJ0b2tlbiI6InBoY19JN3hJY09idHNrcDFWc2FFY0pPdEhycThrWGxrdVg3bGpwdnFWaDNJQ0Z6IiwiZGlzdGluY3RfaWQiOiIwMTkxMmU3Ny1hMjYwLTc5NWMtYjBmYy1lOWE4NzI5MWViNzAiLCJncm91cHMiOnt9fQ%3D%3D"
        decoded = base64_decode(encoded_data)
        decoded_json = json.loads(decoded)

        self.assertEqual(decoded_json["token"], "phc_I7xIcObtskp1VsaEcJOtHrq8kXlkuX7ljpvqVh3ICFz")
        self.assertEqual(decoded_json["distinct_id"], "01912e77-a260-795c-b0fc-e9a87291eb70")
        self.assertEqual(decoded_json["groups"], {})


class TestGetShortUserAgent(TestCase):
    def test_chrome_windows(self):
        request = HttpRequest()
        request.META = {
            "HTTP_USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
        }

        result = get_short_user_agent(request)
        self.assertEqual(result, "Chrome 135.0.0 on Windows 10")

    def test_firefox_macos(self):
        request = HttpRequest()
        request.META = {"HTTP_USER_AGENT": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15) Gecko/20100101 Firefox/131.0"}

        result = get_short_user_agent(request)
        self.assertEqual(result, "Firefox 131.0 on Mac OS X 10.15")

    def test_safari_macos(self):
        request = HttpRequest()
        request.META = {
            "HTTP_USER_AGENT": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
        }

        result = get_short_user_agent(request)
        self.assertEqual(result, "Safari 17.2 on Mac OS X 10.15")

    def test_mobile_chrome_android(self):
        request = HttpRequest()
        request.META = {
            "HTTP_USER_AGENT": "Mozilla/5.0 (Linux; Android 14; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Mobile Safari/537.36"
        }

        result = get_short_user_agent(request)
        self.assertEqual(result, "Chrome Mobile 134.0.0 on Android 14")

    def test_edge_windows(self):
        request = HttpRequest()
        request.META = {
            "HTTP_USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.1847.76"
        }

        result = get_short_user_agent(request)
        self.assertEqual(result, "Edge 134.0.1847 on Windows 10")

    def test_missing_user_agent_header(self):
        request = HttpRequest()
        request.META = {}

        result = get_short_user_agent(request)
        self.assertEqual(result, "")

    def test_empty_user_agent_header(self):
        request = HttpRequest()
        request.META = {"HTTP_USER_AGENT": ""}

        result = get_short_user_agent(request)
        self.assertEqual(result, "")

    def test_version_truncation(self):
        request = HttpRequest()
        request.META = {
            "HTTP_USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.6789.1234 Safari/537.36"
        }

        result = get_short_user_agent(request)
        self.assertIn("Chrome 135.0.6789", result)
        self.assertNotIn("1234", result)


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


def create_group_type_mapping_without_created_at(**kwargs) -> "GroupTypeMapping":
    from posthog.personhog_client.fake_client import personhog_fake_active  # noqa: PLC0415
    from posthog.test.persons import _seed_group_type_mapping_into_fake, create_group_type_mapping  # noqa: PLC0415

    instance = create_group_type_mapping(**kwargs)
    instance.created_at = None
    # Mirror create_group_type_mapping's own branch: when the fake is off (persons-DB-direct tests),
    # it wrote a real row whose created_at defaulted to now(). Null the column with a direct UPDATE
    # over off-Django psycopg so the persons DB genuinely holds a null created_at — making this
    # helper's name true to form for the fake-off path too.
    if not personhog_fake_active():
        from posthog.persons_db import persons_db_connection  # noqa: PLC0415

        with persons_db_connection(writer=True, autocommit=True) as conn, conn.cursor() as cursor:
            cursor.execute("UPDATE posthog_grouptypemapping SET created_at = NULL WHERE id = %s", (instance.pk,))
    _seed_group_type_mapping_into_fake(instance)
    return instance


class TestStrToIntSet(TestCase):
    @parameterized.expand(
        [
            (None, set()),
            ("", set()),
            ("[]", set()),
            ("[1, 2, 3]", {1, 2, 3}),
            ("[1, 1, 2]", {1, 2}),
            ('["1", "2"]', {1, 2}),
            ("invalid", set()),
            ("123", set()),
        ]
    )
    def test_str_to_int_set(self, value, expected):
        assert str_to_int_set(value) == expected


class TestGetIpAddress(TestCase):
    @parameterized.expand(
        [
            # Valid IPv4
            ("192.168.1.1", None, "192.168.1.1"),
            ("8.8.8.8", None, "8.8.8.8"),
            # Valid IPv4 via X-Forwarded-For
            (None, "192.168.1.1", "192.168.1.1"),
            (None, "192.168.1.1, 10.0.0.1", "192.168.1.1"),
            (None, " 192.168.1.1 , 10.0.0.1", "192.168.1.1"),
            # Valid IPv4 with port (Azure gateway format)
            (None, "192.168.1.1:8080", "192.168.1.1"),
            # Valid IPv6
            ("::1", None, "::1"),
            ("2001:db8::1", None, "2001:db8::1"),
            # Valid IPv6 with port (bracketed format)
            (None, "[2001:db8::1]:8080", "2001:db8::1"),
            (None, "[::1]:443", "::1"),
            # IPv6 with brackets but no port
            (None, "[2001:db8::1]", "2001:db8::1"),
            # Invalid/malformed - should return empty string
            (None, "not-an-ip", ""),
            (None, "192.168.1", ""),
            (None, "malicious.payload.here", ""),
            # Empty cases
            (None, None, ""),
            (None, "", ""),
            ("", None, ""),
        ]
    )
    def test_get_ip_address(self, remote_addr, x_forwarded_for, expected):
        request = HttpRequest()
        request.META = {}
        if remote_addr is not None:
            request.META["REMOTE_ADDR"] = remote_addr
        if x_forwarded_for is not None:
            request.META["HTTP_X_FORWARDED_FOR"] = x_forwarded_for
        assert get_ip_address(request) == expected


class TestSharingOverrideProtection(TestCase):
    """Sharing token authenticators must block query param overrides on shared dashboards."""

    def _make_request(self, authenticator, query_params=None):
        factory = RequestFactory()
        django_request = factory.get("/", data=query_params or {})
        request = Request(django_request)
        cast(Any, request)._authenticator = authenticator
        return request

    @parameterized.expand(
        [
            ("access_token_auth",),
            ("password_protected_auth",),
        ]
    )
    def test_filters_override_blocked_for_sharing_authenticators(self, auth_type):
        from posthog.auth import SharingAccessTokenAuthentication, SharingPasswordProtectedAuthentication

        authenticator = (
            SharingAccessTokenAuthentication()
            if auth_type == "access_token_auth"
            else SharingPasswordProtectedAuthentication()
        )
        request = self._make_request(authenticator, query_params={"filters_override": json.dumps({"date_from": "-7d"})})
        dashboard = type("Dashboard", (), {"filters": {"date_from": "-30d"}})()

        result = filters_override_requested_by_client(request, dashboard)

        assert result == {"date_from": "-30d"}

    def test_filters_override_allowed_for_normal_auth(self):
        request = self._make_request(None, query_params={"filters_override": json.dumps({"date_from": "-7d"})})
        dashboard = type("Dashboard", (), {"filters": {"date_from": "-30d"}})()

        result = filters_override_requested_by_client(request, dashboard)

        assert result == {"date_from": "-7d"}

    @parameterized.expand(
        [
            ("access_token_auth",),
            ("password_protected_auth",),
        ]
    )
    @patch(
        "products.product_analytics.backend.api.insight_variable.map_stale_to_latest",
        side_effect=lambda variables, _: variables,
    )
    def test_variables_override_blocked_for_sharing_authenticators(self, auth_type, _mock):
        from posthog.auth import SharingAccessTokenAuthentication, SharingPasswordProtectedAuthentication

        authenticator = (
            SharingAccessTokenAuthentication()
            if auth_type == "access_token_auth"
            else SharingPasswordProtectedAuthentication()
        )
        request = self._make_request(
            authenticator, query_params={"variables_override": json.dumps({"injected": {"value": "evil"}})}
        )
        dashboard = type("Dashboard", (), {"variables": {"var1": {"value": "safe"}}})()

        result = variables_override_requested_by_client(request, dashboard, variables=[])

        assert result == {"var1": {"value": "safe"}}

    @patch(
        "products.product_analytics.backend.api.insight_variable.map_stale_to_latest",
        side_effect=lambda variables, _: variables,
    )
    def test_variables_override_allowed_for_normal_auth(self, _mock):
        request = self._make_request(
            None, query_params={"variables_override": json.dumps({"var1": {"value": "custom"}})}
        )
        dashboard = type("Dashboard", (), {"variables": {"var1": {"value": "default"}}})()

        result = variables_override_requested_by_client(request, dashboard, variables=[])

        assert result == {"var1": {"value": "custom"}}

    @parameterized.expand(
        [
            ("access_token_auth",),
            ("password_protected_auth",),
        ]
    )
    def test_tile_filters_override_blocked_for_sharing_authenticators(self, auth_type):
        from posthog.auth import SharingAccessTokenAuthentication, SharingPasswordProtectedAuthentication

        authenticator = (
            SharingAccessTokenAuthentication()
            if auth_type == "access_token_auth"
            else SharingPasswordProtectedAuthentication()
        )
        request = self._make_request(
            authenticator, query_params={"tile_filters_override": json.dumps({"breakdown": "region"})}
        )
        tile = type("DashboardTile", (), {"filters_overrides": {"breakdown": "country"}})()

        result = tile_filters_override_requested_by_client(request, tile)

        assert result == {"breakdown": "country"}

    def test_tile_filters_override_allowed_for_normal_auth(self):
        request = self._make_request(None, query_params={"tile_filters_override": json.dumps({"breakdown": "region"})})
        tile = type("DashboardTile", (), {"filters_overrides": {"breakdown": "country"}})()

        result = tile_filters_override_requested_by_client(request, tile)

        assert result == {"breakdown": "region"}


class TestTemplateContextHistogram(TestCase):
    @staticmethod
    def _count_for_labels(template_name: str, authenticated: str) -> int:
        from posthog.utils import TEMPLATE_CONTEXT_DURATION_HISTOGRAM

        for metric in TEMPLATE_CONTEXT_DURATION_HISTOGRAM.collect():
            for sample in metric.samples:
                if (
                    sample.name.endswith("_count")
                    and sample.labels.get("template_name") == template_name
                    and sample.labels.get("authenticated") == authenticated
                ):
                    return int(sample.value)
        return 0

    @parameterized.expand(
        [
            ("authenticated", True, "true"),
            ("anonymous", False, "false"),
        ]
    )
    def test_template_context_duration_histogram_uses_correct_authenticated_label(
        self, _name: str, authenticated: bool, expected_label: str
    ):
        request = RequestFactory().get("/")
        # Stash the is_authenticated value via a simple attribute on the request
        # itself; the wrapper reads it via getattr() so it tolerates any user shape.
        request.user = cast(Any, type("FakeUser", (), {"is_authenticated": authenticated})())

        before = self._count_for_labels("index.html", expected_label)

        # Drive only the label-selection wrapper; bypass the heavy inner body so this
        # stays a fast, hermetic unit test of the metric plumbing itself.
        with patch("posthog.utils._build_template_context", return_value={}):
            from posthog.utils import get_context_for_template

            get_context_for_template("index.html", request)

        assert self._count_for_labels("index.html", expected_label) == before + 1


class TestResolveSelfCaptureTeam(TestCase):
    PASSWORD = "testpassword12345"

    def setUp(self):
        super().setUp()
        # resolve_self_capture_team() reads the whole users/teams tables, so each test must
        # control global state. Clear any rows left in the reused test DB; deleting an
        # organization cascades to its projects and teams, and these deletes roll back with
        # the test transaction.
        User.objects.all().delete()
        Organization.objects.all().delete()

    def test_prefers_most_recently_logged_in_users_current_team(self):
        organization = Organization.objects.create(name="Org")
        first_team = Team.objects.create(organization=organization, name="First")
        recent_team = Team.objects.create(organization=organization, name="Recent")

        older_user = User.objects.create_and_join(organization, "older@posthog.com", self.PASSWORD)
        older_user.current_team = first_team
        older_user.last_login = datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))
        older_user.save()

        recent_user = User.objects.create_and_join(organization, "recent@posthog.com", self.PASSWORD)
        recent_user.current_team = recent_team
        recent_user.last_login = datetime(2026, 1, 2, tzinfo=ZoneInfo("UTC"))
        recent_user.save()

        assert resolve_self_capture_team() == recent_team
        assert get_self_capture_team_id() == recent_team.id

    def test_falls_back_to_first_team_when_no_qualifying_user(self):
        organization = Organization.objects.create(name="Org")
        first_team = Team.objects.create(organization=organization, name="First")
        second_team = Team.objects.create(organization=organization, name="Second")

        # A user that has never logged in (last_login is None) must not qualify,
        # even though its current_team points at the second team.
        never_logged_in = User.objects.create_and_join(organization, "never@posthog.com", self.PASSWORD)
        never_logged_in.current_team = second_team
        never_logged_in.last_login = None
        never_logged_in.save()

        assert resolve_self_capture_team() == first_team
        assert get_self_capture_team_id() == first_team.id

    def test_falls_back_to_first_team_when_logged_in_user_has_no_current_team(self):
        organization = Organization.objects.create(name="Org")
        first_team = Team.objects.create(organization=organization, name="First")
        Team.objects.create(organization=organization, name="Second")

        # A logged-in user whose current_team is None still falls back to the first team.
        user = User.objects.create_and_join(organization, "user@posthog.com", self.PASSWORD)
        user.current_team = None
        user.last_login = datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))
        user.save()

        assert resolve_self_capture_team() == first_team
        assert get_self_capture_team_id() == first_team.id

    def test_returns_none_when_there_are_no_teams(self):
        assert resolve_self_capture_team() is None
        assert get_self_capture_team_id() is None


class TestResolveDogfoodFlagsTeam(TestCase):
    PASSWORD = "testpassword12345"

    def setUp(self):
        super().setUp()
        # resolve_dogfood_flags_team() reads the whole teams table, so each test must control
        # global state. Deleting an organization cascades to its projects and teams, and these
        # deletes roll back with the test transaction.
        User.objects.all().delete()
        Organization.objects.all().delete()

    def test_returns_first_team_not_current_team(self):
        # The dogfood-flags team is the first/oldest team (the sync write target), even when the
        # most-recently-logged-in user's current_team is a different team. The two resolvers
        # intentionally diverge: self-capture follows current_team, dogfood-flags follows first team.
        organization = Organization.objects.create(name="Org")
        first_team = Team.objects.create(organization=organization, name="First")
        recent_team = Team.objects.create(organization=organization, name="Recent")

        recent_user = User.objects.create_and_join(organization, "recent@posthog.com", self.PASSWORD)
        recent_user.current_team = recent_team
        recent_user.last_login = datetime(2026, 1, 2, tzinfo=ZoneInfo("UTC"))
        recent_user.save()

        assert resolve_dogfood_flags_team() == first_team
        assert get_dogfood_flags_team_id() == first_team.id
        # Same instance state, the two resolvers point at different teams.
        assert get_self_capture_team_id() == recent_team.id

    def test_returns_none_when_there_are_no_teams(self):
        assert resolve_dogfood_flags_team() is None
        assert get_dogfood_flags_team_id() is None


class TestBuildFlagProvider(TestCase):
    def setUp(self):
        super().setUp()
        # The dogfood branch reads the whole teams table; clear ambient rows so the team we
        # create is the first one. Cascade deletes roll back with the test transaction.
        User.objects.all().delete()
        Organization.objects.all().delete()

    @patch.dict(os.environ, {"POSTHOG_SELF_TEAM_ID": "5"}, clear=False)
    @override_settings(SELF_CAPTURE=True, E2E_TESTING=False)
    def test_explicit_env_team_id_wins_over_self_capture(self):
        assert _build_flag_provider()._resolve_team_id() == 5

    @patch.dict(os.environ, {}, clear=False)
    @override_settings(SELF_CAPTURE=True, E2E_TESTING=False)
    def test_self_capture_routes_to_dogfood_first_team(self):
        os.environ.pop("POSTHOG_SELF_TEAM_ID", None)
        organization = Organization.objects.create(name="Org")
        first_team = Team.objects.create(organization=organization, name="First")

        assert _build_flag_provider()._resolve_team_id() == first_team.id

    @patch.dict(os.environ, {}, clear=False)
    @override_settings(SELF_CAPTURE=False, E2E_TESTING=False)
    def test_falls_back_to_team_2_off_self_capture(self):
        os.environ.pop("POSTHOG_SELF_TEAM_ID", None)

        assert _build_flag_provider()._resolve_team_id() == 2

    @patch.dict(os.environ, {}, clear=False)
    @override_settings(SELF_CAPTURE=True, E2E_TESTING=True)
    def test_e2e_overrides_self_capture_to_team_2(self):
        os.environ.pop("POSTHOG_SELF_TEAM_ID", None)

        assert _build_flag_provider()._resolve_team_id() == 2


VALID_PRELOAD_MANIFEST = {
    "css": "static/index-ABC123.css",
    "font": "static/assets/Inter-DEF456.woff2",
    "js": ["static/index-GHI789.js", "static/chunk-APP111.js"],
    "authenticatedJs": ["static/chunk-SHELL222.js", "static/chunk-APP111.js"],
}


class TestReadPreloadManifest(SimpleTestCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_dir = tmp.name

    def _write_manifest(self, content: str) -> str:
        path = os.path.join(self.tmp_dir, "preload-manifest.json")
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_resolves_unauthenticated_urls_as_written_by_the_build(self):
        path = self._write_manifest(json.dumps(VALID_PRELOAD_MANIFEST))

        assert _read_preload_manifest(path, include_authenticated_shell=False) == (
            "static/index-ABC123.css",
            ("static/index-GHI789.js", "static/chunk-APP111.js"),
            "static/assets/Inter-DEF456.woff2",
        )

    def test_appends_authenticated_chunks_deduplicated(self):
        path = self._write_manifest(json.dumps(VALID_PRELOAD_MANIFEST))

        _, js_urls, _ = _read_preload_manifest(path, include_authenticated_shell=True)

        assert js_urls == ("static/index-GHI789.js", "static/chunk-APP111.js", "static/chunk-SHELL222.js")

    def test_missing_manifest_resolves_empty(self):
        missing = os.path.join(self.tmp_dir, "missing.json")

        assert _read_preload_manifest(missing, include_authenticated_shell=True) == ("", (), "")

    @parameterized.expand(
        [
            ("corrupt_json", '{"css": "static/index.css", "js": ['),
            ("js_not_a_list", json.dumps({**VALID_PRELOAD_MANIFEST, "js": "static/index.js"})),
            ("js_entry_not_a_string", json.dumps({**VALID_PRELOAD_MANIFEST, "js": [{"file": "chunk.js"}]})),
            ("css_not_a_string", json.dumps({**VALID_PRELOAD_MANIFEST, "css": ["static/index.css"]})),
        ]
    )
    def test_malformed_manifest_resolves_empty_instead_of_garbage(self, _name: str, content: str) -> None:
        path = self._write_manifest(content)

        assert _read_preload_manifest(path, include_authenticated_shell=True) == ("", (), "")
