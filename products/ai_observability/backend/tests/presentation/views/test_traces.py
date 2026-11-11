from datetime import timedelta
from types import SimpleNamespace

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.api.query import CONCURRENCY_LIMIT_RETRY_AFTER_SECONDS
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot, RateLimit
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models import Team
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events

from products.ai_observability.backend.logic.traces import trace_queries

from .trace_fixtures import GENERATION, T0, TRACE_EVENT, create_trace, encode_segment, restrict_property


class TestTraceViewSet(ClickhouseTestMixin, APIBaseTest):
    def _url(self, segment: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/"

    @time_machine.travel(T0 + timedelta(days=1), tick=False)
    def test_availability_reads_both_tables_with_a_read_key_and_stays_in_the_project(self) -> None:
        create_trace(self.team, "application,trace")
        other_team = Team.objects.create(organization=self.organization, name="other")
        bulk_create_events(
            [
                {
                    "event": "$ai_generation",
                    "event_uuid": event_id,
                    "distinct_id": "user-1",
                    "team": team,
                    "timestamp": T0,
                    "properties": {"$ai_trace_id": trace_id},
                }
                for event_id, team, trace_id in [
                    (GENERATION, self.team, "evaluator/trace"),
                    (TRACE_EVENT, other_team, "other-trace"),
                ]
            ]
        )
        key = self.create_personal_api_key_with_scopes(["llm_analytics:read"])
        self.client.logout()
        headers = {"authorization": f"Bearer {key}"}

        with self.capture_select_queries() as queries:
            response = self.client.post(
                self._url("availability"),
                {"trace_ids": ["application,trace", "evaluator/trace"]},
                format="json",
                headers=headers,
            )

        assert response.status_code == 200
        assert response.json() == {"available_trace_ids": ["application,trace", "evaluator/trace"]}
        probes = [query for query in queries if "FROM system.columns" not in query]
        assert len(probes) == 2
        for query in probes:
            self.assertQueryMatchesSnapshot(query)

        with self.capture_select_queries() as queries:
            response = self.client.post(
                self._url("availability"),
                {"trace_ids": ["missing", "other-trace"]},
                format="json",
                headers=headers,
            )
        assert response.status_code == 200
        assert response.json() == {"available_trace_ids": []}
        probes = [query for query in queries if "FROM system.columns" not in query]
        assert len(probes) == 2
        for query in probes:
            self.assertQueryMatchesSnapshot(query)

        with self.capture_select_queries() as queries:
            response = self.client.post(
                self._url("availability"),
                {"trace_ids": ["application,trace", "application,trace"]},
                format="json",
                headers=headers,
            )
        assert response.status_code == 200
        assert response.json() == {"available_trace_ids": ["application,trace"]}
        assert len([query for query in queries if "FROM system.columns" not in query]) == 1

    def test_availability_rejects_more_than_two_traces(self) -> None:
        response = self.client.post(self._url("availability"), {"trace_ids": ["one", "two", "three"]}, format="json")

        assert response.status_code == 400

    def test_availability_preserves_known_traces_when_the_fallback_times_out(self) -> None:
        with patch.object(
            trace_queries,
            "execute_hogql_query",
            side_effect=[SimpleNamespace(results=[["application,trace"]]), ClickHouseQueryTimeOut()],
        ):
            response = self.client.post(
                self._url("availability"),
                {"trace_ids": ["application,trace", "evaluator/trace"]},
                format="json",
            )

        assert response.status_code == 200
        assert response.json() == {"available_trace_ids": ["application,trace"]}

    def test_numbers_steps_that_share_a_name(self) -> None:
        bulk_create_ai_events(
            [
                {
                    "event": "$ai_generation",
                    "event_uuid": f"00000000-0000-0000-0000-00000000000{index}",
                    "distinct_id": "user-1",
                    "team": self.team,
                    "timestamp": T0 + timedelta(seconds=index),
                    "properties": {
                        "$ai_trace_id": "trace-1",
                        "$ai_parent_id": "trace-1",
                        "$ai_span_name": "openai.chat",
                    },
                }
                for index in (1, 2)
            ]
        )

        response = self.client.get(self._url(encode_segment("trace-1")))

        [root] = response.json()["tree"]
        assert [root["label"], *(child["label"] for child in root["children"])] == [
            "openai.chat #1",
            "openai.chat #2",
            "openai.chat #3",
        ]

    @parameterized.expand([("plain id", "trace-1"), ("id with a dot", "run.42"), ("id with a slash", "a/b")])
    def test_returns_the_trace_in_camel_case(self, _name: str, trace_id: str) -> None:
        create_trace(self.team, trace_id)

        response = self.client.get(self._url(encode_segment(trace_id)))

        assert response.status_code == 200
        body = response.json()
        assert body["tree"][0]["id"] == trace_id
        assert body["tree"][0]["children"][0]["id"] == "00000000-0000-0000-0000-000000000001"
        assert body["totals"]["inputTokens"] == 3
        assert body["threadNodeIds"] == ["00000000-0000-0000-0000-000000000001"]
        assert body["defaultNodeId"] == "00000000-0000-0000-0000-000000000001"
        assert body["nodeIdsByAlias"] == {}

    @parameterized.expand(
        [
            ("visible", False, {"branch": "feat/rag", "repo": "acme/app"}),
            ("restricted for the viewer", True, None),
        ]
    )
    def test_returns_the_git_branch_unless_the_viewer_may_not_read_it(
        self, _name: str, restricted: bool, expected: dict[str, str] | None
    ) -> None:
        if restricted:
            restrict_property(self, "$ai_git_branch")
        create_trace(self.team, extra_properties={"$ai_git_branch": "feat/rag", "$ai_git_repo": "acme/app"})

        assert self.client.get(self._url(encode_segment("trace-1"))).json()["git"] == expected

    @parameterized.expand([("unknown trace", False), ("another team's trace", True)])
    def test_not_found(self, _name: str, other_team_owns_it: bool) -> None:
        if other_team_owns_it:
            create_trace(Team.objects.create(organization=self.organization, name="other"), "trace-2")

        assert self.client.get(self._url(encode_segment("trace-2"))).status_code == 404

    @parameterized.expand(
        [
            ("malformed timestamp hint", encode_segment("trace-1"), {"timestamp_hint": "yesterday"}),
            (
                "timestamp hint at the end of time",
                encode_segment("trace-1"),
                {"timestamp_hint": "9999-12-31T23:59:59Z"},
            ),
            (
                "timestamp hint at the start of time",
                encode_segment("trace-1"),
                {"timestamp_hint": "0001-01-01T00:00:00Z"},
            ),
            ("unencoded trace id", "trace-1", {}),
        ]
    )
    def test_rejects_a_malformed_request(self, _name: str, segment: str, query: dict[str, str]) -> None:
        create_trace(self.team, "trace-1")

        assert self.client.get(self._url(segment), query).status_code == 400

    @parameterized.expand(
        [
            (f"{reader} {read}", with_api_key, exhausted_limit, suffix)
            for reader, with_api_key, exhausted_limit in [
                ("browser session", False, "app_per_org"),
                ("personal api key", True, "api_per_team"),
            ]
            for read, suffix in [
                ("trace", ""),
                ("node", f"nodes/{encode_segment('trace-1')}/"),
                ("raw node", f"nodes/{encode_segment('trace-1')}/raw/"),
                ("evaluations", "evaluations/"),
                ("clusters", "clusters/?created_at=2026-09-01T10:00:00Z"),
                ("search", "search/?q=invoice"),
            ]
        ]
    )
    def test_throttles_when_the_query_concurrency_limit_is_exhausted(
        self, _name: str, with_api_key: bool, exhausted_limit: str, suffix: str
    ) -> None:
        create_trace(self.team, "trace-1")
        headers = {}
        if with_api_key:
            key = self.create_personal_api_key_with_scopes(["llm_analytics:read", "ai_observability_clusters:read"])
            headers["authorization"] = f"Bearer {key}"
            self.client.logout()

        def use(limiter: RateLimit, *args: object, **kwargs: object) -> ConcurrencySlot | None:
            if limiter.limit_name == exhausted_limit:
                raise ConcurrencyLimitExceeded(exhausted_limit)
            return None

        with (
            patch("posthog.clickhouse.client.limit.TEST", False),
            patch.object(RateLimit, "use", autospec=True, side_effect=use),
        ):
            response = self.client.get(self._url(encode_segment("trace-1")) + suffix, headers=headers)

        assert response.status_code == 429
        assert response["Retry-After"] == str(CONCURRENCY_LIMIT_RETRY_AFTER_SECONDS)
