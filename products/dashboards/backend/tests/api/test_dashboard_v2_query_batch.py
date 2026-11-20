import json
import datetime as dt
from collections.abc import Iterator
from typing import Any, cast

import time_machine
from posthog.test.base import APIBaseTest, NonAtomicAPIBaseTest
from unittest.mock import MagicMock, patch

from django.db import connection
from django.http import StreamingHttpResponse
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext

import requests
from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import PersonalAPIKey
from posthog.models.organization import OrganizationMembership
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.dashboards.backend.facade.contracts import QueryBatchInput, QueryBatchTarget
from products.dashboards.backend.facade.enums import QueryBatchLanguage
from products.dashboards.backend.v2.query_batch import InvalidTarget, resolve_query, to_posthog_date
from products.dashboards.backend.v2.telemetry import Step, pick_step
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
        if flag in ("metrics", "logs-metrics-snuffle-api"):
            return True
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


_NOW = dt.datetime(2026, 9, 19, 12, 0, 37, tzinfo=dt.UTC)
_LAST_HOUR = {"from": "now-1h", "to": "now"}


def _telemetry(language: str, query: str, **options: Any) -> dict:
    return {"target": {"refId": language, "language": language, "query": query}, "time": _LAST_HOUR, **options}


def _snuffle(status_code: int, payload: dict) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.json.return_value = payload
    response.headers = {}
    return response


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
        with patch(
            "posthog.api.snuffle_proxy.internal_requests.request",
            return_value=_snuffle(200, _matrix(int(_NOW.timestamp()) - 3600)),
        ) as request:
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
        rejected = _snuffle(400, {"status": "error", "errorType": "bad_data", "error": "parse error at char 5"})
        with patch("posthog.api.snuffle_proxy.internal_requests.request", return_value=rejected):
            lines = self._lines([_telemetry(language, query)])

        self.assertEqual(lines, [{"i": 0, "error": "parse error at char 5"}])

    def test_a_relative_logql_range_moves_with_the_clock(self) -> None:
        sent_ends = []
        for moment in (_NOW, _NOW + dt.timedelta(minutes=5)):
            with (
                time_machine.travel(moment, tick=False),
                patch(
                    "posthog.api.snuffle_proxy.internal_requests.request", return_value=_snuffle(200, _matrix(0))
                ) as request,
            ):
                self._lines([_telemetry("logql", 'sum(rate({service_name="api"}[1m]))')])
            sent_ends.append(float(request.call_args.kwargs["data"]["end"]))

        self.assertEqual(sent_ends[1] - sent_ends[0], 300)

    @parameterized.expand([("promql", "up"), ("logql", '{service_name="api"}')])
    def test_flag_off_runs_nothing(self, language: str, query: str) -> None:
        self.flag_on_for_project = self.team.pk + 1
        with patch("posthog.api.snuffle_proxy.internal_requests.request") as request:
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

    def test_logql_has_no_scrape_interval_floor(self) -> None:
        self.assertEqual(
            pick_step(dt.timedelta(hours=1), max_data_points=None, min_interval=None, is_promql=False),
            Step(seconds=15, interval="second_15"),
        )

    def test_rejects_an_unknown_min_interval(self) -> None:
        target = QueryBatchTarget(ref_id="a", language=QueryBatchLanguage.PROMQL, query="up")

        with self.assertRaises(InvalidTarget):
            resolve_query(QueryBatchInput(target=target, date_from="now-1h", date_to="now", interval="hour"))
