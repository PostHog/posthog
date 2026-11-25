import gc
import json
import asyncio
import datetime as dt
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import aclosing, contextmanager
from threading import Event, Semaphore
from typing import Any, cast
from urllib.parse import parse_qsl
from uuid import uuid4
from zoneinfo import ZoneInfo

import time_machine
from posthog.test.base import APIBaseTest, NonAtomicAPIBaseTest
from unittest.mock import MagicMock, patch

from django.db import connection
from django.http import StreamingHttpResponse
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext

import httpx
import requests
from parameterized import parameterized
from rest_framework import status

from posthog.api.services.query import process_query_dict, run_planned_query
from posthog.clickhouse.query_tagging import get_query_tag_value, get_query_tags
from posthog.constants import AvailableFeature
from posthog.models import PersonalAPIKey
from posthog.models.organization import OrganizationMembership
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.test.waiting import wait_until

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.dashboards.backend.facade.api import query_batch_stream
from products.dashboards.backend.facade.contracts import QueryBatchInput, QueryBatchTarget
from products.dashboards.backend.facade.enums import QueryBatchLanguage
from products.dashboards.backend.v2 import query_batch as query_batch_module
from products.dashboards.backend.v2.query_batch import InvalidTarget, QueryBatch, resolve_query, to_posthog_date
from products.dashboards.backend.v2.telemetry import Step, pick_step, returns_log_lines, time_range
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
        self.dashboard_v2_users: set[str] | None = None
        patcher = patch("posthoganalytics.feature_enabled", side_effect=self._flag_enabled)
        patcher.start()
        cast(Any, self).addCleanup(patcher.stop)

    def _flag_enabled(self, flag: str, distinct_id: str, **kwargs: Any) -> bool:
        groups = kwargs.get("groups") or {}
        if flag == "dashboard-v2-users":
            email = (kwargs.get("person_properties") or {}).get("email")
            return self.dashboard_v2_users is None or email in self.dashboard_v2_users
        if flag in ("metrics", "logs-metrics-snuffle-api"):
            return True
        return flag == "dashboard-v2" and groups.get("project") == str(self.flag_on_for_project)

    def _batch(self, queries: list[dict], headers: dict[str, str] | None = None, **body: Any) -> Any:
        return self.client.post(
            f"/api/environments/{self.team.pk}/dashboard_v2/query_batch/",
            {"queries": queries, **body},
            format="json",
            headers=headers,
        )

    def _lines(self, queries: list[dict], headers: dict[str, str] | None = None, **body: Any) -> list[dict]:
        response = self._batch(queries, headers, **body)
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
            (
                "member_not_in_the_audience",
                lambda test: setattr(test, "dashboard_v2_users", set()),
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

    def test_a_miss_runs_tagged_as_a_query_and_a_raise_still_ends_the_stream(self) -> None:
        features: list[str | None] = []

        def run(*args: Any, **kwargs: Any) -> Any:
            # Strict query tagging rejects untagged ClickHouse queries, so a miss must carry the request's feature.
            features.append(get_query_tag_value("feature"))
            raise RuntimeError("boom")

        with patch("products.dashboards.backend.v2.query_batch.process_query_dict", side_effect=run):
            lines = self._lines([_insight("$pageview")])

        self.assertEqual(lines, [{"i": 0, "error": "The query failed."}])
        self.assertEqual(features, ["query"])

    def test_misses_past_a_users_query_share_are_busy_and_the_share_comes_back(self) -> None:
        # A worker hands its share back after its line is streamed, so the test waits for both hand-backs.
        ended = Semaphore(0)
        query_ended = query_batch_module._query_ended

        def counted(keys: tuple[Any, ...], future: Any) -> None:
            query_ended(keys, future)
            ended.release()

        with (
            patch("products.dashboards.backend.v2.query_batch.MAX_RUN_QUERIES_PER_USER", 2),
            patch("products.dashboards.backend.v2.query_batch.process_query_dict", return_value={"results": []}),
            patch.object(query_batch_module, "_query_ended", counted),
        ):
            lines = self._lines([_insight("$pageview"), _insight("$autocapture"), _insight("$pageleave")])
            self.assertTrue(all(ended.acquire(timeout=10) for _ in range(2)))

        self.assertEqual(
            [line.get("error") for line in lines],
            [None, None, "Too many dashboards are loading at once. Try again shortly."],
        )
        self.assertEqual(query_batch_module._org_queries, {})

    def test_a_batch_that_cannot_start_its_workers_gives_its_shares_back(self) -> None:
        with (
            patch("products.dashboards.backend.v2.query_batch.ThreadPoolExecutor.submit", side_effect=RuntimeError),
            self.assertRaises(RuntimeError),
        ):
            self._lines([_insight("$pageview"), _insight("$autocapture")])

        self.assertEqual(query_batch_module._org_queries, {})
        self.assertEqual(query_batch_module._org_batches, {})

    def test_a_disconnect_cancels_running_queries_with_tags_set(self) -> None:
        cancelled = Event()
        seen: list[tuple[str | None, str | None]] = []

        def cancel(**kwargs: Any) -> None:
            seen.append((get_query_tag_value("product"), get_query_tag_value("feature")))
            cancelled.set()

        batch = QueryBatch(
            team=self.team,
            user=self.user,
            inputs=[
                QueryBatchInput(
                    target=QueryBatchTarget(ref_id="a", language=QueryBatchLanguage.HOGQL, query="select 1"),
                    date_from="now-7d",
                    date_to="now",
                    cache_only=True,
                )
            ],
            dashboard_id=None,
            client_query_id="dashboard-v2-batch-test",
        )
        batch._active.add("dashboard-v2-batch-test-0")
        with patch("products.dashboards.backend.v2.query_batch.cancel_query_on_cluster", side_effect=cancel):
            batch._close(complete=False)
            self.assertTrue(cancelled.wait(timeout=5))
            batch._idle.set()
        batch._open.release()

        self.assertEqual(seen[0], ("product_analytics", "query"))

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

    @parameterized.expand([("stream_deadline", "MAX_STREAM_SECONDS"), ("idle_deadline", "MAX_IDLE_SECONDS")])
    def test_a_client_that_stops_reading_gives_its_place_back(self, _name: str, deadline: str) -> None:
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

        with patch("products.dashboards.backend.v2.query_batch.MAX_OPEN_BATCHES_PER_ORG", 1):
            with (
                patch(f"products.dashboards.backend.v2.query_batch.{deadline}", 0.0),
                patch("products.dashboards.backend.v2.query_batch.STALLED_RESPONSE_GRACE_SECONDS", 0.0),
            ):
                ended = asyncio.run(ended_by_the_batch())
            next_batch = b"".join(cast(Iterator[bytes], open_batch(asynchronous=False)))

        self.assertTrue(ended)
        self.assertEqual(json.loads(next_batch)["result"]["cache"]["hit"], False)

    def test_a_batch_dropped_before_it_streams_stops_its_watchdog(self) -> None:
        batch = QueryBatch(
            team=self.team, user=self.user, inputs=_cache_only_inputs(), dashboard_id=None, client_query_id="dropped"
        )
        watchdog = batch._watchdog
        del batch
        gc.collect()
        watchdog.join(timeout=5)

        self.assertFalse(watchdog.is_alive())

    def test_a_batch_whose_cancel_thread_cannot_start_still_frees_its_slot(self) -> None:
        batch = QueryBatch(
            team=self.team, user=self.user, inputs=_cache_only_inputs(), dashboard_id=None, client_query_id="no-thread"
        )
        batch._watchdog.cancel()
        self.addCleanup(batch._open.release)
        batch._admitted = query_batch_module._admit_batch(batch._shares)
        batch._active.add("running")

        with patch.object(query_batch_module, "Thread", side_effect=RuntimeError), self.assertRaises(RuntimeError):
            batch._close(False)

        self.assertEqual(query_batch_module._org_batches, {})

    def test_a_client_still_reading_a_long_line_is_not_idle(self) -> None:
        # The reader receives 16 bytes per idle window, so a line split into 8-byte slices marks progress twice per
        # window, while the same line handed over whole would take several windows to arrive.
        idle_bytes_per_second = 16 / query_batch_module.MAX_IDLE_SECONDS
        now = [0.0]
        with (
            patch.object(query_batch_module, "monotonic", lambda: now[0]),
            patch.object(query_batch_module, "MAX_STREAM_SECONDS", 1e9),
            patch.object(query_batch_module, "PULL_SLICE_BYTES", 8),
        ):
            batch = QueryBatch(
                team=self.team, user=self.user, inputs=_cache_only_inputs(), dashboard_id=None, client_query_id="slow"
            )
            batch._watchdog.cancel()
            received = b""
            for piece in batch.stream():
                now[0] += len(piece) / idle_bytes_per_second
                self.assertIsNotNone(batch._check_deadlines())
                received += piece

        self.assertGreater(len(received), 32)
        self.assertEqual(json.loads(received)["i"], 0)


class TestQueryBatchRuns(_QueryBatchMixin, NonAtomicAPIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

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

    def test_each_run_is_tagged_for_the_query_log_with_its_tile_target_and_traceparent(self) -> None:
        traceparent = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        node = json.dumps({"query": _events_node("$pageview")["source"]})
        queries: list[dict[str, Any]] = [
            {"target": {"refId": "A", "language": "insight", "query": node}, "time": _LAST_7_DAYS, "tile": "t-1"},
            {"target": {"refId": "C", "language": "hogql", "query": "select 1"}, "time": _LAST_7_DAYS},
        ]
        tags: list[tuple[str | None, str | None]] = []

        def tagged(*args: Any, **kwargs: Any) -> Any:
            current = get_query_tags()
            tags.append((current.client_query_id, current.traceparent))
            return process_query_dict(*args, **kwargs)

        with patch.object(query_batch_module, "process_query_dict", side_effect=tagged):
            self._lines(queries, headers={"traceparent": traceparent})
            # A malformed header is dropped rather than written into query_log.
            self._lines(
                [{"target": {"refId": "D", "language": "hogql", "query": "select 2"}, "time": _LAST_7_DAYS}],
                headers={"traceparent": "not a trace"},
            )

        self.assertEqual([parent for _id, parent in tags], [traceparent, traceparent, None])
        self.assertCountEqual(
            [query_id.rsplit("-", 1)[0] for query_id, _parent in tags[:2] if query_id],
            ["dashboard-v2-batch-none-t_1-A", "dashboard-v2-batch-none-none-C"],
        )

    def test_a_stale_refresh_runs_under_its_target_query_id_and_traceparent(self) -> None:
        traceparent = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        query = resolve_query(
            QueryBatchInput(
                target=QueryBatchTarget(ref_id="a", language=QueryBatchLanguage.HOGQL, query="select 1"),
                date_from="now-7d",
                date_to="now",
            )
        )
        runs: list[tuple[str | None, str | None, str | None]] = []

        def tagged(*args: Any, **kwargs: Any) -> None:
            current = get_query_tags()
            runs.append((kwargs.get("query_id"), current.client_query_id, current.traceparent))

        self.assertTrue(query_batch_module._refresh_slots.acquire(blocking=False))
        # On the refresh pool as in production, since a refresh closes its thread's database connections.
        with patch.object(query_batch_module, "process_query_dict", side_effect=tagged):
            query_batch_module._refresh_pool.submit(
                query_batch_module._refresh_all,
                team=self.team,
                user=self.user,
                dashboard_id=None,
                queries=[("dashboard-v2-batch-none-t_1-a-0123abcd", query)],
                shares=(),
                traceparent=traceparent,
            ).result(timeout=10)

        query_id = "dashboard-v2-batch-none-t_1-a-0123abcd"
        self.assertEqual(runs, [(query_id, query_id, traceparent)])


class TestQueryShares(SimpleTestCase):
    def test_one_users_large_batches_leave_room_for_another_organization(self) -> None:
        org_a, org_b = uuid4(), uuid4()
        member, colleague, other_org = (
            query_batch_module._share_keys(org, user) for org, user in ((org_a, 1), (org_a, 2), (org_b, 3))
        )
        with (
            patch.object(query_batch_module, "MAX_RUN_QUERIES", 4),
            patch.object(query_batch_module, "MAX_RUN_QUERIES_PER_ORG", 3),
            patch.object(query_batch_module, "MAX_RUN_QUERIES_PER_USER", 2),
            patch.object(query_batch_module, "_org_queries", {}),
        ):
            granted = [
                query_batch_module._reserve_queries(member, 500),
                query_batch_module._reserve_queries(member, 500),
                query_batch_module._reserve_queries(colleague, 500),
                query_batch_module._reserve_queries(other_org, 500),
            ]

        self.assertEqual(granted, [2, 0, 1, 1])


_NOW = dt.datetime(2026, 9, 19, 12, 0, 37, tzinfo=dt.UTC)
_LAST_HOUR = {"from": "now-1h", "to": "now"}


def _telemetry(language: str, query: str, **options: Any) -> dict:
    return {"target": {"refId": language, "language": language, "query": query}, "time": _LAST_HOUR, **options}


def _snuffle(status_code: int, payload: dict) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.json.return_value = payload
    response.iter_content.return_value = [json.dumps(payload).encode()]
    response.headers = {}
    return response


@contextmanager
def _snuffle_requests(status_code: int = 200, payload: dict | None = None) -> Iterator[MagicMock]:
    payload = payload if payload is not None else _matrix(0)
    with patch(
        "posthog.api.snuffle_proxy.internal_requests.request", return_value=_snuffle(status_code, payload)
    ) as sent:

        def handle(request: httpx.Request) -> httpx.Response:
            sent(request.method, str(request.url), data=dict(parse_qsl(request.content.decode())))
            return httpx.Response(status_code, json=payload)

        with patch(
            "posthog.api.snuffle_proxy.internal_httpx_async_client",
            side_effect=lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs),
        ):
            yield sent


def _matrix(start: int) -> dict:
    return {
        "status": "success",
        "data": {"resultType": "matrix", "result": [{"metric": {"job": "api"}, "values": [[start, "2"]]}]},
    }


class TestQueryBatchTelemetryTargets(_QueryBatchMixin, NonAtomicAPIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self._enable_flag()
        self.enterContext(
            override_settings(SNUFFLE_METRICS_URL="http://metrics.test", SNUFFLE_APM_URL="http://logs.test")
        )

    def _snuffle_calls(self, request: MagicMock) -> dict[str, dict]:
        return {call.args[1]: call.kwargs["data"] for call in request.call_args_list}

    @time_machine.travel(_NOW, tick=False)
    def test_runs_promql_through_the_metrics_query_cache_and_logql_uncached(self) -> None:
        queries = [
            _telemetry("promql", "sum(rate(http_requests_total[5m]))"),
            _telemetry("logql", 'sum(count_over_time({service_name="api"}[1m]))'),
        ]
        with _snuffle_requests(200, _matrix(int(_NOW.timestamp()) - 3600)) as request:
            promql, logql = self._lines(queries)
            sent = self._snuffle_calls(request)
            request.reset_mock()
            cached_promql, rerun_logql = self._lines(queries)

        self.assertEqual(promql["result"]["cache"]["hit"], False)
        self.assertEqual(promql["result"]["result"]["results"][0]["labels"], {"job": "api"})
        self.assertEqual(sent["http://metrics.test/api/v1/query_range"]["step"], "60")
        self.assertEqual(logql["result"]["result"]["results"]["resultType"], "matrix")
        logql_sent = sent["http://logs.test/loki/api/v1/query_range"]
        self.assertEqual(logql_sent["step"], "15")
        self.assertEqual(float(logql_sent["end"]), _NOW.timestamp() - 7)
        self.assertEqual(cached_promql["result"]["cache"], {**promql["result"]["cache"], "hit": True})
        self.assertEqual(rerun_logql["result"]["cache"]["hit"], False)
        self.assertEqual(list(self._snuffle_calls(request)), ["http://logs.test/loki/api/v1/query_range"])

    @parameterized.expand([("promql", "sum(rate(up[5m])"), ("logql", "{service_name=")])
    def test_a_rejected_query_is_an_error_line(self, language: str, query: str) -> None:
        with _snuffle_requests(400, {"status": "error", "errorType": "bad_data", "error": "parse error at char 5"}):
            lines = self._lines([_telemetry(language, query)])

        self.assertEqual(lines, [{"i": 0, "error": "parse error at char 5"}])

    def test_a_relative_logql_range_moves_with_the_clock(self) -> None:
        sent_ends = []
        for moment in (_NOW, _NOW + dt.timedelta(minutes=5)):
            with (
                time_machine.travel(moment, tick=False),
                _snuffle_requests() as request,
            ):
                self._lines([_telemetry("logql", 'sum(rate({service_name="api"}[1m]))')])
            sent_ends.append(float(request.call_args.kwargs["data"]["end"]))

        self.assertEqual(sent_ends[1] - sent_ends[0], 300)

    def test_an_oversized_logql_response_is_an_error_line_not_a_buffered_body(self) -> None:
        with (
            patch("products.dashboards.backend.v2.telemetry.MAX_LOGQL_RESPONSE_BYTES", 10),
            _snuffle_requests(),
        ):
            lines = self._lines([_telemetry("logql", 'sum(rate({service_name="api"}[1m]))')])

        self.assertIn("too much data", lines[0]["error"])

    def test_a_logql_body_that_outlasts_the_timeout_is_an_error_line(self) -> None:
        class StalledBody(httpx.AsyncByteStream):
            async def __aiter__(self) -> AsyncIterator[bytes]:
                yield b"{"
                await asyncio.Event().wait()

        response = httpx.Response(200, stream=StalledBody())
        with (
            override_settings(SNUFFLE_APM_TIMEOUT_SECONDS=0.01),
            patch(
                "posthog.api.snuffle_proxy.internal_httpx_async_client",
                side_effect=lambda **kwargs: httpx.AsyncClient(
                    transport=httpx.MockTransport(lambda _request: response), **kwargs
                ),
            ),
        ):
            lines = self._lines([_telemetry("logql", 'sum(rate({service_name="api"}[1m]))')])

        self.assertEqual(lines, [{"i": 0, "error": "The LogQL query timed out. Try a shorter date range."}])
        self.assertTrue(response.is_closed)

    @parameterized.expand([("headers", False), ("body", True)])
    @patch.object(query_batch_module, "MAX_BATCHES_PER_USER", query_batch_module.MAX_BATCHES_PER_ORG)
    @patch.object(query_batch_module, "MAX_OPEN_BATCHES_PER_USER", query_batch_module.MAX_OPEN_BATCHES_PER_ORG)
    def test_disconnecting_logql_batches_closes_upstream_and_releases_admission(
        self, _name: str, send_headers: bool
    ) -> None:
        inputs = [
            QueryBatchInput(
                target=QueryBatchTarget(ref_id="logs", language=QueryBatchLanguage.LOGQL, query='{service_name="api"}'),
                date_from="now-1h",
                date_to="now",
            )
        ]
        batches = [
            QueryBatch(
                team=self.team, user=self.user, inputs=inputs, dashboard_id=None, client_query_id=f"disconnect-{index}"
            )
            for index in range(4)
        ]

        async def exercise() -> list[dict]:
            started: asyncio.Queue[None] = asyncio.Queue()
            disconnected: asyncio.Queue[None] = asyncio.Queue()
            request_count = 0
            loop = asyncio.get_running_loop()

            class StalledBody(httpx.AsyncByteStream):
                async def __aiter__(self) -> AsyncIterator[bytes]:
                    loop.call_soon_threadsafe(started.put_nowait, None)
                    yield b"{"
                    await asyncio.Event().wait()

                async def aclose(self) -> None:
                    loop.call_soon_threadsafe(disconnected.put_nowait, None)

            async def upstream(request: httpx.Request) -> httpx.Response:
                nonlocal request_count
                request_count += 1
                self.assertEqual(request.headers["X-Team-ID"], str(self.team.pk))
                if request_count <= 3:
                    if send_headers:
                        return httpx.Response(200, stream=StalledBody())
                    loop.call_soon_threadsafe(started.put_nowait, None)
                    try:
                        await asyncio.Event().wait()
                    finally:
                        loop.call_soon_threadsafe(disconnected.put_nowait, None)
                return httpx.Response(200, json=_matrix(0))

            async def consume(batch: QueryBatch) -> list[dict]:
                async with aclosing(cast(Any, batch.astream())) as stream:
                    return [json.loads(chunk) async for chunk in stream if chunk.strip()]

            readers: list[asyncio.Task[list[dict]]] = []
            try:
                with (
                    override_settings(SNUFFLE_APM_TIMEOUT_SECONDS=60),
                    patch(
                        "posthog.api.snuffle_proxy.internal_httpx_async_client",
                        side_effect=lambda **kwargs: httpx.AsyncClient(
                            transport=httpx.MockTransport(upstream), **kwargs
                        ),
                    ),
                ):
                    readers = [asyncio.create_task(consume(batch)) for batch in batches[:3]]
                    for _ in readers:
                        await asyncio.wait_for(started.get(), timeout=10)
                    for reader in readers:
                        reader.cancel()
                    await asyncio.gather(*readers, return_exceptions=True)
                    for _ in readers:
                        await asyncio.wait_for(disconnected.get(), timeout=5)
                    await asyncio.to_thread(
                        wait_until,
                        lambda: not query_batch_module._org_batches,
                    )
                    return await asyncio.wait_for(consume(batches[3]), timeout=10)
            finally:
                for reader in readers:
                    reader.cancel()
                await asyncio.gather(*readers, return_exceptions=True)

        try:
            lines = asyncio.run(exercise())
        finally:
            for batch in batches:
                batch._close(complete=False)
                batch._watchdog.cancel()
                batch._open.release()

        self.assertEqual(lines[0]["result"]["result"]["results"], _matrix(0)["data"])

    @patch.object(query_batch_module, "MAX_OPEN_BATCHES_PER_USER", query_batch_module.MAX_OPEN_BATCHES_PER_ORG)
    def test_timeout_and_disconnect_hold_admission_until_http_cleanup_finishes(self) -> None:
        inputs = [
            QueryBatchInput(
                target=QueryBatchTarget(ref_id="logs", language=QueryBatchLanguage.LOGQL, query='{service_name="api"}'),
                date_from="now-1h",
                date_to="now",
            )
        ]
        batches = [
            QueryBatch(
                team=self.team, user=self.user, inputs=inputs, dashboard_id=None, client_query_id=f"cleanup-{index}"
            )
            for index in range(3)
        ]

        async def exercise() -> None:
            loop = asyncio.get_running_loop()
            closing: asyncio.Queue[Callable[[], None]] = asyncio.Queue()
            cleanup_complete = Event()
            request_count = 0

            class GatedBody(httpx.AsyncByteStream):
                async def __aiter__(self) -> AsyncIterator[bytes]:
                    yield b"{"
                    await asyncio.Event().wait()

                async def aclose(self) -> None:
                    worker_loop = asyncio.get_running_loop()
                    allow_close = asyncio.Event()

                    def release() -> None:
                        try:
                            worker_loop.call_soon_threadsafe(allow_close.set)
                        except RuntimeError:
                            pass

                    loop.call_soon_threadsafe(closing.put_nowait, release)
                    await allow_close.wait()
                    cleanup_complete.set()

            def upstream(_request: httpx.Request) -> httpx.Response:
                nonlocal request_count
                request_count += 1
                return (
                    httpx.Response(200, stream=GatedBody())
                    if request_count == 1
                    else httpx.Response(200, json=_matrix(0))
                )

            async def consume(batch: QueryBatch) -> list[dict]:
                async with aclosing(cast(Any, batch.astream())) as stream:
                    return [json.loads(chunk) async for chunk in stream if chunk.strip()]

            release_cleanup: Callable[[], None] | None = None
            reader: asyncio.Task[list[dict]] | None = None
            worker: asyncio.Future[None] | None = None
            with (
                override_settings(SNUFFLE_APM_TIMEOUT_SECONDS=0.01),
                patch("products.dashboards.backend.v2.query_batch.MAX_BATCHES_PER_ORG", 1),
                patch(
                    "posthog.api.snuffle_proxy.internal_httpx_async_client",
                    side_effect=lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(upstream), **kwargs),
                ),
            ):
                try:
                    reader = asyncio.create_task(consume(batches[0]))
                    release_cleanup = await asyncio.wait_for(closing.get(), timeout=5)
                    worker = asyncio.wrap_future(batches[0]._futures[0])
                    reader.cancel()
                    await asyncio.gather(reader, return_exceptions=True)
                    await asyncio.to_thread(wait_until, batches[0]._logql_cancelled.is_set)
                    done, _ = await asyncio.wait({worker}, timeout=1)
                    self.assertFalse(done, "The worker finished before its HTTP response cleanup was released")
                    blocked = await consume(batches[1])
                    self.assertEqual(
                        blocked, [{"i": 0, "error": "Too many dashboards are loading at once. Try again shortly."}]
                    )
                    release_cleanup()
                    release_cleanup = None
                    await asyncio.wait_for(asyncio.gather(worker, return_exceptions=True), timeout=5)
                    self.assertTrue(cleanup_complete.is_set())
                    await asyncio.to_thread(wait_until, lambda: not query_batch_module._org_batches)
                    with override_settings(SNUFFLE_APM_TIMEOUT_SECONDS=60):
                        fresh = await consume(batches[2])
                    self.assertEqual(fresh[0]["result"]["result"]["results"], _matrix(0)["data"])
                finally:
                    if release_cleanup is not None:
                        release_cleanup()
                    if reader is not None:
                        reader.cancel()
                        await asyncio.gather(reader, return_exceptions=True)
                    if worker is not None:
                        await asyncio.wait_for(asyncio.gather(worker, return_exceptions=True), timeout=5)

        try:
            asyncio.run(exercise())
        finally:
            for batch in batches:
                batch._close(complete=False)
                batch._watchdog.cancel()
                batch._open.release()

    @patch("products.dashboards.backend.v2.telemetry.budget_enabled", return_value=True)
    @patch("products.dashboards.backend.v2.telemetry.api_queries_budget_enforcement_enabled", return_value=True)
    @patch("products.dashboards.backend.v2.telemetry.refill_and_read", return_value=0.0)
    @patch("products.dashboards.backend.v2.telemetry.events_last_year_for", return_value=0)
    def test_an_exhausted_byte_budget_refuses_logql_before_reaching_snuffle(
        self, events_last_year: MagicMock, *_mocks: MagicMock
    ) -> None:
        logql = _telemetry("logql", 'sum(rate({service_name="api"}[1m]))')
        with _snuffle_requests() as request:
            lines = self._lines([logql, {**logql, "target": {**logql["target"], "refId": "b"}}])

        refused = "This project has used its query budget for now. Try again later."
        self.assertEqual(lines, [{"i": 0, "error": refused}, {"i": 1, "error": refused}])
        request.assert_not_called()
        # The budget spec reads Postgres, so the batch resolves it once for all its LogQL targets.
        events_last_year.assert_called_once_with(self.team.pk)

    def test_a_huge_relative_date_fails_only_its_own_panel(self) -> None:
        lines = self._lines([{**_telemetry("promql", "up"), "time": {"from": "now-99999999y", "to": "now"}}])

        self.assertEqual(lines, [{"i": 0, "error": "Unsupported time expression: 'now-99999999y'."}])

    @parameterized.expand([("no_access", "none", False), ("viewer", "viewer", True)])
    def test_a_member_runs_logql_only_with_logs_access(self, _name: str, access_level: str, runs: bool) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(resource="logs", team=self.team, access_level=access_level)
        self.client.force_login(self._create_user("logs-member@posthog.com", level=OrganizationMembership.Level.MEMBER))

        with _snuffle_requests() as request:
            [line] = self._lines([_telemetry("logql", 'sum(rate({service_name="api"}[1m]))')])

        if runs:
            self.assertEqual(line["result"]["result"]["results"], _matrix(0)["data"])
        else:
            self.assertEqual(
                line,
                {"i": 0, "error": "Access control failure. You don't have `viewer` access to the `logs` resource."},
            )
            request.assert_not_called()

    @parameterized.expand([("promql", "up"), ("logql", '{service_name="api"}')])
    def test_flag_off_runs_nothing(self, language: str, query: str) -> None:
        self.flag_on_for_project = self.team.pk + 1
        with _snuffle_requests() as request:
            response = self._batch([_telemetry(language, query)])

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        request.assert_not_called()


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

    @parameterized.expand(
        [
            ("rate_limited_per_team", {"kind": "ErrorTrackingFingerprintProjectionQuery"}),
            ("direct_warehouse", {"kind": "HogQLQuery", "query": "select 1", "connectionId": "abc"}),
            ("managed_trino", {"kind": "HogQLQuery", "query": "select 1", "executionTarget": "managed_trino"}),
            (
                "warehouse_native_experiment",
                {
                    "kind": "ExperimentQuery",
                    "experiment_id": 1,
                    "metric": {
                        "metric_type": "mean",
                        "source": {
                            "kind": "ExperimentWarehouseNativeNode",
                            "connection_id": "abc",
                            "query": "select 1",
                        },
                    },
                },
            ),
        ]
    )
    def test_rejects_a_query_a_batch_cannot_limit_or_cancel(self, _name: str, query: dict) -> None:
        target = QueryBatchTarget(ref_id="a", language=QueryBatchLanguage.INSIGHT, query=json.dumps({"query": query}))

        with self.assertRaises(InvalidTarget):
            resolve_query(QueryBatchInput(target=target, date_from="now-7d", date_to="now"))

    @parameterized.expand(
        [
            # (name, time from, min interval, max data points, MetricsQuery interval)
            ("an_hour_stays_on_the_scrape_interval", "now-1h", None, None, "minute"),
            ("a_week_coarsens_to_fit_the_points", "now-7d", None, None, "hour"),
            ("more_points_give_a_finer_step", "now-7d", None, 3000, "minute_5"),
            ("the_min_interval_wins", "now-1h", "5m", None, "minute_5"),
        ]
    )
    def test_promql_keeps_its_range_relative_and_picks_a_stable_step(
        self, _name: str, date_from: str, interval: str | None, max_points: int | None, expected: str
    ) -> None:
        target = QueryBatchTarget(ref_id="a", language=QueryBatchLanguage.PROMQL, query="up")

        resolved = resolve_query(
            QueryBatchInput(
                target=target, date_from=date_from, date_to="now", interval=interval, max_data_points=max_points
            )
        )

        self.assertEqual(resolved.query["dateRange"], {"date_from": to_posthog_date(date_from), "date_to": None})
        self.assertEqual(resolved.query["interval"], expected)

    def test_months_are_calendar_months_and_naive_dates_are_in_the_project_timezone(self) -> None:
        at = dt.datetime(2026, 11, 20, 12, tzinfo=dt.UTC)
        berlin = ZoneInfo("Europe/Berlin")

        self.assertEqual(time_range("now-1M", "now", at=at).start, dt.datetime(2026, 10, 20, 12, tzinfo=dt.UTC))
        self.assertEqual(
            time_range("2026-11-01T00:00:00", "now", tz=berlin, at=at).start,
            dt.datetime(2026, 11, 1, tzinfo=berlin),
        )
        across_dst = time_range("now-30m", "now", tz=berlin, at=dt.datetime(2026, 3, 29, 1, 15, tzinfo=dt.UTC))
        self.assertEqual(across_dst.end - across_dst.start, dt.timedelta(minutes=30))

    @parameterized.expand(
        [
            ("a_min_interval_past_the_ladder", "now-30d", "2w", None),
            ("a_range_too_long_for_the_points", "now-30d", None, 1),
        ]
    )
    def test_promql_rejects_a_step_past_a_week(
        self, _name: str, date_from: str, interval: str | None, max_points: int | None
    ) -> None:
        target = QueryBatchTarget(ref_id="a", language=QueryBatchLanguage.PROMQL, query="up")

        with self.assertRaises(InvalidTarget):
            resolve_query(
                QueryBatchInput(
                    target=target, date_from=date_from, date_to="now", interval=interval, max_data_points=max_points
                )
            )

    @parameterized.expand(
        [
            ("a_min_interval_past_the_ladder", dt.timedelta(days=30), "2w", None, 1209600),
            ("a_range_too_long_for_the_points", dt.timedelta(days=30), None, 1, 2592000),
        ]
    )
    def test_logql_keeps_both_step_constraints_past_the_ladder(
        self, _name: str, span: dt.timedelta, interval: str | None, max_points: int | None, expected: int
    ) -> None:
        step = pick_step(span, max_data_points=max_points, min_interval=interval, is_promql=False)

        self.assertEqual(step.seconds, expected)

    @parameterized.expand(
        [
            ("a_filter_quoting_a_function_name", '{service_name="api"} |= "rate("', True),
            ("a_backtick_filter", '{service_name="api"} |~ `count_over_time(`', True),
            ("a_metric_query", 'sum(rate({service_name="api"} |= "x" [1m]))', False),
            ("an_escaped_quote_inside_a_filter", r'{service_name="api"} |= "a\"rate("', True),
            ("an_unterminated_filter", '{service_name="api"} |= "rate(' + '\\"' * 20000, True),
        ]
    )
    def test_classifies_logql_by_its_functions_not_its_strings(self, _name: str, logql: str, expected: bool) -> None:
        self.assertEqual(returns_log_lines(logql), expected)

    def test_logql_has_no_scrape_interval_floor(self) -> None:
        self.assertEqual(
            pick_step(dt.timedelta(hours=1), max_data_points=None, min_interval=None, is_promql=False),
            Step(seconds=15, interval="second_15"),
        )

    def test_rejects_an_unknown_min_interval(self) -> None:
        target = QueryBatchTarget(ref_id="a", language=QueryBatchLanguage.PROMQL, query="up")

        with self.assertRaises(InvalidTarget):
            resolve_query(QueryBatchInput(target=target, date_from="now-1h", date_to="now", interval="hour"))
