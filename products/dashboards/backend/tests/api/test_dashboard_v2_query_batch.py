import json
from collections.abc import Iterator
from typing import Any, cast

from posthog.test.base import APIBaseTest, NonAtomicAPIBaseTest
from unittest.mock import patch

from django.db import connection
from django.http import StreamingHttpResponse
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.dashboards.backend.facade.contracts import QueryBatchInput, QueryBatchTarget
from products.dashboards.backend.facade.enums import QueryBatchLanguage
from products.dashboards.backend.v2.query_batch import InvalidTarget, resolve_query, to_posthog_date
from products.event_definitions.backend.models import PropertyDefinition

_LAST_7_DAYS = {"from": "now-7d", "to": "now"}


def _events_node(event: str) -> dict:
    return {"kind": "DataTableNode", "source": {"kind": "EventsQuery", "select": ["count()"], "event": event}}


def _insight(event: str, **options: Any) -> dict:
    return {
        "target": {"refId": event, "language": "insight", "query": json.dumps({"query": _events_node(event)})},
        "time": _LAST_7_DAYS,
        **options,
    }


class _QueryBatchMixin:
    client: Any
    team: Any

    def _enable_flag(self) -> None:
        self.flag_on_for_project: int | None = self.team.pk
        patcher = patch("posthoganalytics.feature_enabled", side_effect=self._flag_enabled)
        patcher.start()
        cast(Any, self).addCleanup(patcher.stop)

    def _flag_enabled(self, flag: str, distinct_id: str, **kwargs: Any) -> bool:
        groups = kwargs.get("groups") or {}
        return flag == "dashboard-v2" and groups.get("project") == str(self.flag_on_for_project)

    def _batch(self, queries: list[dict], **body: Any) -> Any:
        return self.client.post(
            f"/api/environments/{self.team.pk}/dashboard_v2/query_batch/", {"queries": queries, **body}, format="json"
        )

    def _lines(self, queries: list[dict], **body: Any) -> list[dict]:
        response = self._batch(queries, **body)
        cast(Any, self).assertEqual(response.status_code, status.HTTP_200_OK, getattr(response, "data", None))
        # Not closed: closing sends request_finished, which closes the test's database connection.
        content = b"".join(cast(Iterator[bytes], cast(StreamingHttpResponse, response).streaming_content))
        return sorted((json.loads(line) for line in content.splitlines() if line.strip()), key=lambda line: line["i"])

    def _warm_via_query_endpoint(self, event: str) -> dict:
        # What a PostHog dashboard sends for a tile over the last 7 days.
        response = self.client.post(
            f"/api/environments/{self.team.pk}/query/",
            {
                "query": _events_node(event),
                "filters_override": {"date_from": "-7d", "date_to": None},
                "refresh": "blocking",
            },
            format="json",
        )
        cast(Any, self).assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()


class TestQueryBatchCacheReads(_QueryBatchMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._enable_flag()

    def test_reads_what_the_query_endpoint_cached_without_reading_insights(self) -> None:
        warm = self._warm_via_query_endpoint("$pageview")

        with CaptureQueriesContext(connection) as queries:
            hit, miss, bad = self._lines(
                [
                    _insight("$pageview", cacheOnly=True),
                    _insight("$autocapture", cacheOnly=True),
                    {"target": {"refId": "x", "language": "insight", "query": "not json"}, "time": _LAST_7_DAYS},
                ]
            )

        self.assertEqual(
            hit["result"]["cache"],
            {"key": warm["cache_key"], "fetchedAt": warm["last_refresh"], "stale": False, "hit": True},
        )
        self.assertEqual(hit["result"]["result"]["results"], warm["results"])
        self.assertEqual(miss["result"]["cache"]["hit"], False)
        self.assertIsNone(miss["result"]["result"])
        self.assertIn("error", bad)
        self.assertEqual(
            [
                q["sql"]
                for q in queries.captured_queries
                if "posthog_dashboarditem" in q["sql"] or "posthog_dashboardtile" in q["sql"]
            ],
            [],
        )

    def test_a_property_restricted_member_never_reads_another_users_entry(self) -> None:
        warm = self._warm_via_query_endpoint("$pageview")
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        member = self._create_user("member@posthog.com", level=OrganizationMembership.Level.MEMBER)
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=PropertyDefinition.objects.create(
                team=self.team, name="secret_prop", property_type="String", type=PropertyDefinition.Type.EVENT
            ),
            organization_member=OrganizationMembership.objects.get(user=member, organization=self.organization),
            access_level=PropertyAccessLevel.NONE.value,
        )
        [owner] = self._lines([_insight("$pageview", cacheOnly=True)])

        self.client.force_login(member)
        [restricted] = self._lines([_insight("$pageview", cacheOnly=True)])

        self.assertEqual(owner["result"]["cache"]["hit"], True)
        self.assertEqual(restricted["result"]["cache"]["hit"], False)
        self.assertIsNone(restricted["result"]["result"])
        self.assertNotEqual(restricted["result"]["cache"]["key"], warm["cache_key"])

    @parameterized.expand(
        [
            (
                "flag_off",
                lambda test: setattr(test, "flag_on_for_project", test.team.pk + 1),
                {},
                status.HTTP_404_NOT_FOUND,
            ),
            ("unknown_dashboard", lambda test: None, {"dashboard": 999999}, status.HTTP_404_NOT_FOUND),
        ]
    )
    def test_refuses(self, _name: str, arrange: Any, body: dict, expected: int) -> None:
        arrange(self)

        response = self._batch([_insight("$pageview", cacheOnly=True)], **body)

        self.assertEqual(response.status_code, expected, response.content)


class TestQueryBatchRuns(_QueryBatchMixin, NonAtomicAPIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._enable_flag()

    def test_runs_misses_in_the_stream_and_serves_them_from_cache_next_time(self) -> None:
        queries = [
            _insight("$pageview"),
            {
                "target": {
                    "refId": "sql",
                    "language": "hogql",
                    "query": "select count() from events where {filters}",
                },
                "time": _LAST_7_DAYS,
            },
        ]

        first = self._lines(queries)
        second = self._lines(queries)

        self.assertEqual([line["result"]["cache"]["hit"] for line in first], [False, False])
        self.assertEqual([line["result"]["cache"]["hit"] for line in second], [True, True])
        self.assertEqual(
            [line["result"]["cache"]["key"] for line in second], [line["result"]["cache"]["key"] for line in first]
        )


class TestResolveQuery(SimpleTestCase):
    @parameterized.expand(
        [
            ("now", "now", None),
            ("days", "now-14d", "-14d"),
            ("minutes", "now-30m", "-30M"),
            ("months", "now-3M", "-3m"),
            ("seconds_round_up_to_a_minute", "now-90s", "-2M"),
            ("absolute_date", "2026-01-01", "2026-01-01"),
        ]
    )
    def test_keeps_relative_ranges_relative(self, _name: str, expression: str, expected: str | None) -> None:
        self.assertEqual(to_posthog_date(expression), expected)

    def test_a_target_that_pins_its_range_keeps_it(self) -> None:
        target = QueryBatchTarget(
            ref_id="a",
            language=QueryBatchLanguage.INSIGHT,
            query=json.dumps({"query": _events_node("$pageview"), "filters": {"date_from": "-90d"}}),
        )

        resolved = resolve_query(QueryBatchInput(target=target, date_from="now-7d", date_to="now"))

        self.assertEqual(resolved.filters, {"date_from": "-90d"})

    def test_rejects_an_unknown_time_expression(self) -> None:
        with self.assertRaises(InvalidTarget):
            to_posthog_date("yesterday")
