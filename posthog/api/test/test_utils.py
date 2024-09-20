import json
import requests
from typing import Any, cast

from django.http import HttpRequest
from django.test.client import RequestFactory
from parameterized import parameterized
from rest_framework import status

from posthog.api.utils import (
    PaginationMode,
    check_definition_ids_inclusion_field_sql,
    format_paginated_url,
    get_data,
    get_target_entity,
    raise_if_user_provided_url_unsafe,
    safe_clickhouse_string,
    PublicIPOnlyHttpAdapter,
    unparsed_hostname_in_allowed_url_list,
)
from posthog.models.filters.filter import Filter
from posthog.test.base import BaseTest


def return_true():
    return True


class TestUtils(BaseTest):
    def test_get_data(self):
        # No data in request
        data, error_response = get_data(HttpRequest())
        self.assertEqual(data, None)
        self.assertEqual(error_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual("No data found" in json.loads(error_response.getvalue())["detail"], True)

        # Valid request with event
        request = HttpRequest()
        request.method = "POST"
        request.POST = {"data": json.dumps({"event": "some event"})}
        data, error_response = get_data(request)
        self.assertEqual(data, {"event": "some event"})
        self.assertEqual(error_response, None)

    def test_format_paginated_url(self):
        request = lambda url: cast(Any, RequestFactory().get(url))

        self.assertEqual(
            format_paginated_url(request("/api/some_url"), offset=0, page_size=10),
            "http://testserver/api/some_url?offset=10",
        )
        self.assertEqual(
            format_paginated_url(request("/api/some_url?offset=0"), offset=0, page_size=10),
            "api/some_url?offset=10",
        )
        self.assertEqual(
            format_paginated_url(
                request("/api/some_url?offset=0"),
                offset=0,
                page_size=10,
                mode=PaginationMode.previous,
            ),
            None,
        )
        self.assertEqual(
            format_paginated_url(
                request("/api/some_url?offset=0"),
                offset=20,
                page_size=10,
                mode=PaginationMode.previous,
            ),
            "api/some_url?offset=0",
        )

    def test_get_target_entity(self):
        request = lambda url: cast(Any, RequestFactory().get(url))
        filter = Filter(
            data={
                "entity_id": "$pageview",
                "entity_type": "events",
                "events": [{"id": "$pageview", "type": "events"}],
            }
        )
        entity = get_target_entity(filter)

        assert entity.id == "$pageview"
        assert entity.type == "events"
        assert entity.math is None

        filter = Filter(
            data={
                "entity_id": "$pageview",
                "entity_type": "events",
                "entity_math": "unique_group",
                "events": [
                    {"id": "$pageview", "type": "events", "math": "unique_group"},
                    {"id": "$pageview", "type": "events"},
                ],
            }
        )
        entity = get_target_entity(filter)

        assert entity.id == "$pageview"
        assert entity.type == "events"
        assert entity.math == "unique_group"

    def test_check_definition_ids_inclusion_field_sql(self):
        definition_ids = [
            "",
            None,
            '["1fcefbef-7ea1-42fd-abca-4848b53133c0", "c8452399-8a10-4142-864d-6f2ca8c65154"]',
        ]

        expected_ids_list = [
            [],
            [],
            [
                "1fcefbef-7ea1-42fd-abca-4848b53133c0",
                "c8452399-8a10-4142-864d-6f2ca8c65154",
            ],
        ]

        for raw_ids, expected_ids in zip(definition_ids, expected_ids_list):
            ordered_expected_ids = list(set(expected_ids))
            # Property
            query, ids = check_definition_ids_inclusion_field_sql(raw_ids, True, "named_key")
            assert query == "(id = ANY (%(named_key)s::uuid[]))"
            assert ids == ordered_expected_ids

            # Event
            query, ids = check_definition_ids_inclusion_field_sql(raw_ids, False, "named_key")
            assert query == "(id = ANY (%(named_key)s::uuid[]))"
            assert ids == ordered_expected_ids

    # keep in sync with posthog/plugin-server/tests/utils.test.ts::safeClickhouseString
    def test_safe_clickhouse_string_valid_strings(self):
        valid_strings = [
            "$autocapture",
            "correlation analyzed",
            "docs_search_used",
            "$$plugin_metrics",
            "996f3e2f-830b-42f0-b2b8-df42bb7f7144",
            "some?819)389**^371=2++211!!@==-''''..,,weird___id",
            """
                form.form-signin:attr__action="/signup"attr__class="form-signin"attr__method="post"nth-child="1"nth-of-type="1";body:nth-child="2"nth-of-type="1"
            """,
            """
                a:attr__href="/signup"href="/signup"nth-child="1"nth-of-type="1"text="Create one here.";p:nth-child="8"nth-of-type="1";form.form-signin:attr__action="/login"attr__class="form-signin"attr__method="post"nth-child="1"nth-of-type="1";body:nth-child="2"nth-of-type="1"
            """,
            """
                input:nth-child="7"nth-of-type="3";form.form-signin:attr__action="/signup"attr__class="form-signin"attr__method="post"nth-child="1"nth-of-type="1";body:nth-child="2"nth-of-type="1"
            """,
            """
                a.nav-link:attr__class="nav-link"attr__href="/actions"href="/actions"nth-child="1"nth-of-type="1"text="Actions";li:nth-child="2"nth-of-type="2";ul.flex-sm-column.nav:attr__class="nav flex-sm-column"nth-child="1"nth-of-type="1";div.bg-light.col-md-2.col-sm-3.flex-shrink-1.pt-3.sidebar:attr__class="col-sm-3 col-md-2 sidebar flex-shrink-1 bg-light pt-3"attr__style="min-height: 100vh;"nth-child="1"nth-of-type="1";div.flex-column.flex-fill.flex-sm-row.row:attr__class="row flex-fill flex-column flex-sm-row"nth-child="1"nth-of-type="1";div.container-fluid.d-flex.flex-grow-1:attr__class="container-fluid flex-grow-1 d-flex"nth-child="1"nth-of-type="1";div:attr__id="root"attr_id="root"nth-child="1"nth-of-type="1";body:nth-child="2"nth-of-type="1"
            """,
        ]

        for s in valid_strings:
            self.assertEqual(safe_clickhouse_string(s), s)

    # keep in sync with posthog/plugin-server/tests/utils.test.ts::safeClickhouseString
    def test_safe_clickhouse_string_surrogates(self):
        # flake8: noqa
        self.assertEqual(safe_clickhouse_string("foo \ud83d\ bar"), "foo \\ud83d\\ bar")
        self.assertEqual(safe_clickhouse_string("\ud83d\ bar"), "\\ud83d\\ bar")
        self.assertEqual(safe_clickhouse_string("\ud800\ \ud803\ "), "\\ud800\\ \\ud803\\ ")

    # keep in sync with posthog/plugin-server/tests/utils.test.ts::safeClickhouseString
    def test_safe_clickhouse_string_unicode_non_surrogates(self):
        self.assertEqual(safe_clickhouse_string("✨"), "✨")
        self.assertEqual(safe_clickhouse_string("foo \u2728\ bar"), "foo \u2728\ bar")
        self.assertEqual(safe_clickhouse_string("💜 \u1f49c\ 💜"), "💜 \u1f49c\ 💜")

    def test_raise_if_user_provided_url_unsafe(self):
        # Sync test cases with plugin-server/src/utils/fetch.test.ts
        raise_if_user_provided_url_unsafe("https://google.com?q=20")  # Safe
        raise_if_user_provided_url_unsafe("https://posthog.com")  # Safe
        raise_if_user_provided_url_unsafe("https://posthog.com/foo/bar")  # Safe, with path
        raise_if_user_provided_url_unsafe("https://posthog.com:443")  # Safe, good port
        raise_if_user_provided_url_unsafe("https://1.1.1.1")  # Safe, public IP
        self.assertRaisesMessage(ValueError, "No hostname", lambda: raise_if_user_provided_url_unsafe(""))
        self.assertRaisesMessage(ValueError, "No hostname", lambda: raise_if_user_provided_url_unsafe("@@@"))
        self.assertRaisesMessage(
            ValueError,
            "No hostname",
            lambda: raise_if_user_provided_url_unsafe("posthog.com"),
        )
        self.assertRaisesMessage(
            ValueError,
            "Scheme must be either HTTP or HTTPS",
            lambda: raise_if_user_provided_url_unsafe("ftp://posthog.com"),
        )
        self.assertRaisesMessage(
            ValueError,
            "Internal hostname",
            lambda: raise_if_user_provided_url_unsafe("http://localhost"),
        )
        self.assertRaisesMessage(
            ValueError,
            "Internal hostname",
            lambda: raise_if_user_provided_url_unsafe("http://192.168.0.5"),
        )
        self.assertRaisesMessage(
            ValueError,
            "Internal hostname",
            lambda: raise_if_user_provided_url_unsafe("http://0.0.0.0"),
        )
        self.assertRaisesMessage(
            ValueError,
            "Internal hostname",
            lambda: raise_if_user_provided_url_unsafe("http://10.0.0.24"),
        )
        self.assertRaisesMessage(
            ValueError,
            "Internal hostname",
            lambda: raise_if_user_provided_url_unsafe("http://172.20.0.21"),
        )
        self.assertRaisesMessage(
            ValueError,
            "Invalid hostname",
            lambda: raise_if_user_provided_url_unsafe("http://fgtggggzzggggfd.com"),
        )  # Non-existent

    def test_public_ip_only_adapter(self):
        address = "http://localhost:8123"  # Clickhouse's HTTP port

        # We can connect OK by default
        self.assertTrue(requests.get(address).ok)

        # Adding the adapter makes the connection fail
        session = requests.Session()
        session.mount("http://", PublicIPOnlyHttpAdapter())
        self.assertRaisesMessage(
            ValueError,
            "Internal IP",
            lambda: session.get(address),
        )

    @parameterized.expand(
        [
            ("empty allowlist", [], "http://localhost:8123", False),
            ("no allowlist", None, "http://localhost:8123", False),
            ("allowlist is empty string", ["     "], "http://localhost:8123", False),
            ("allowlist is not a domain", ["this little piggy"], "http://localhost:8123", False),
            ("needle is the empty string", ["http://localhost"], "", False),
            ("needle is whitespace", ["http://localhost"], "    ", False),
            ("needle is absent", ["http://localhost"], None, False),
            ("single element matches", ["http://localhost"], "http://localhost:8123", True),
            ("single element matches but is url encoded", ["http://localhost"], "http%3A%2F%2Flocalhost:8123", True),
            ("multi element matches", ["http://localhost", "http://posthog.com"], "http://localhost:8123", True),
            ("scheme should be ignored", ["ftp://localhost"], "https://localhost:8123", True),
            ("needle is not in allowlist", ["http://localhost"], "http://posthog.com:8123", False),
            ("regex needle is not in allowlist", ["http://*.com"], "http://localhost:8123", False),
            ("regex needle is in allowlist", ["http://*.com"], "http://posthog.com:8123", True),
        ]
    )
    def test_unparsed_hostname_in_allowed_url_list(
        self, _name: str, allowlist: list[str], needle: str | None, expected: bool
    ) -> None:
        assert unparsed_hostname_in_allowed_url_list(allowlist, needle) == expected
