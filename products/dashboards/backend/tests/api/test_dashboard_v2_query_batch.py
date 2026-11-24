import gc
import json
import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import aclosing
from typing import Any, cast

from posthog.test.base import APIBaseTest, NonAtomicAPIBaseTest
from unittest.mock import patch

from django.db import connection
from django.http import StreamingHttpResponse
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog.api.services.query import run_planned_query
from posthog.constants import AvailableFeature
from posthog.models import PersonalAPIKey
from posthog.models.organization import OrganizationMembership
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.dashboards.backend.facade.api import query_batch_stream
from products.dashboards.backend.facade.contracts import QueryBatchInput, QueryBatchTarget
from products.dashboards.backend.facade.enums import QueryBatchLanguage
from products.dashboards.backend.v2.query_batch import InvalidTarget, QueryBatch, resolve_query, to_posthog_date
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


def _cache_only_inputs() -> list[QueryBatchInput]:
    target = QueryBatchTarget(
        ref_id="a",
        language=QueryBatchLanguage.INSIGHT,
        query=json.dumps({"query": _events_node("$pageview")}),
    )
    return [QueryBatchInput(target=target, date_from="now-7d", date_to="now", cache_only=True)]


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

    def test_refuses_a_personal_api_key(self) -> None:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="batch", user=self.user, secure_value=hash_key_value(value), scopes=["query:read"]
        )
        self.client.logout()

        response = self.client.post(
            f"/api/environments/{self.team.pk}/dashboard_v2/query_batch/",
            {"queries": [_insight("$pageview", cacheOnly=True)]},
            format="json",
            headers={"Authorization": f"Bearer {value}"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)

    def test_a_query_that_raises_still_ends_the_stream_with_an_error_line(self) -> None:
        with patch("products.dashboards.backend.v2.query_batch.process_query_dict", side_effect=RuntimeError("boom")):
            lines = self._lines([_insight("$pageview")])

        self.assertEqual(lines, [{"i": 0, "error": "The query failed."}])

    def test_an_oversized_entry_is_read_once_however_many_panels_repeat_it(self) -> None:
        self._warm_via_query_endpoint("$pageview")
        (hit,) = self._lines([_insight("$pageview", cacheOnly=True)])
        too_large = {
            "error": "The cached results in this request are too large to send together. Request fewer panels at once."
        }
        budget = len(json.dumps(hit, separators=(",", ":"))) - 64
        # Room for a full chunk of error lines, so the second chunk is read rather than refused outright.
        self.assertGreater(budget, 5 * len(json.dumps(too_large, separators=(",", ":"))))

        with (
            patch("products.dashboards.backend.v2.query_batch.MAX_READY_BYTES", budget),
            patch("products.dashboards.backend.v2.query_batch.run_planned_query", wraps=run_planned_query) as reads,
        ):
            lines = self._lines([_insight("$pageview", cacheOnly=True)] * 7)

        self.assertEqual(lines, [{"i": i, **too_large} for i in range(7)])
        self.assertEqual(reads.call_count, 1)

    def test_a_client_that_stops_reading_gives_its_place_back_when_the_stream_expires(self) -> None:
        inputs = _cache_only_inputs()

        def open_batch(asynchronous: bool) -> Any:
            return query_batch_stream(
                team=self.team,
                user=self.user,
                inputs=inputs,
                dashboard_id=None,
                client_query_id="stalled",
                asynchronous=asynchronous,
            )

        async def stop_reading(stream: AsyncIterator[bytes]) -> None:
            # Mirrors the ASGI handler, which closes the body when its send is cancelled.
            async with aclosing(cast(Any, stream)) as body:
                async for _line in body:
                    await asyncio.Event().wait()

        async def ended_by_the_batch() -> bool:
            reader = asyncio.create_task(stop_reading(cast(AsyncIterator[bytes], open_batch(asynchronous=True))))
            await asyncio.wait({reader}, timeout=10)
            ended = reader.cancelled()
            reader.cancel()
            return ended

        with (
            patch("products.dashboards.backend.v2.query_batch.MAX_OPEN_BATCHES_PER_ORG", 1),
            patch("products.dashboards.backend.v2.query_batch.MAX_STREAM_SECONDS", 0.0),
            patch("products.dashboards.backend.v2.query_batch.STALLED_RESPONSE_GRACE_SECONDS", 0.0),
        ):
            ended = asyncio.run(ended_by_the_batch())
            next_batch = b"".join(cast(Iterator[bytes], open_batch(asynchronous=False)))

        self.assertTrue(ended)
        self.assertEqual(json.loads(next_batch), {"i": 0, "error": "The dashboard took too long to load. Try again."})

    def test_a_batch_dropped_before_it_streams_stops_its_watchdog(self) -> None:
        batch = QueryBatch(
            team=self.team, user=self.user, inputs=_cache_only_inputs(), dashboard_id=None, client_query_id="dropped"
        )
        watchdog = batch._watchdog
        del batch
        gc.collect()
        watchdog.join(timeout=5)

        self.assertFalse(watchdog.is_alive())


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

    def test_rejects_a_query_kind_that_query_rate_limits_per_team(self) -> None:
        target = QueryBatchTarget(
            ref_id="a",
            language=QueryBatchLanguage.INSIGHT,
            query=json.dumps({"query": {"kind": "ErrorTrackingFingerprintProjectionQuery"}}),
        )

        with self.assertRaises(InvalidTarget):
            resolve_query(QueryBatchInput(target=target, date_from="now-7d", date_to="now"))
