import json
from datetime import timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.utils import timezone

from loginas import settings as loginas_settings
from parameterized import parameterized

from posthog.api.query import CONCURRENCY_LIMIT_RETRY_AFTER_SECONDS
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot, RateLimit
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models import Team, User
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events
from posthog.models.oauth import OAuthAccessToken, OAuthApplication

from products.ai_observability.backend.logic.traces import trace_queries

from .trace_fixtures import (
    GENERATION,
    T0,
    TRACE_EVENT,
    QuerySlotRecorder,
    TraceEvents,
    create_trace,
    encode_segment,
    restrict_property,
)

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse


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
        assert body["totalsPartial"] is False
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
                (
                    "dataset item",
                    f"nodes/{encode_segment('trace-1')}/dataset_item/?timestamp_hint=2026-09-01T10:00:00Z",
                ),
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


CUSTOM_EXPRESSION = json.dumps([{"type": "hogql", "key": "properties.$ai_model = 'gpt-test'"}])


@time_machine.travel(T0 + timedelta(days=1), tick=False)
class TestTraceListViewSet(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.events = TraceEvents(self.team)

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/"

    def _get(
        self, params: dict[str, str | int] | None = None, *, scopes: list[str] | None = None
    ) -> "_MonkeyPatchedResponse":
        headers = {}
        if scopes is not None:
            headers["authorization"] = f"Bearer {self.create_personal_api_key_with_scopes(scopes)}"
            self.client.logout()
        return self.client.get(self._url(), params, headers=headers)

    def _listed(self, params: dict[str, str | int] | None = None) -> list[str]:
        response = self._get(params)
        assert response.status_code == 200, response.json()
        return [item["id"] for item in response.json()["items"]]

    def test_lists_traces_with_a_read_key(self) -> None:
        self.events.seed_traces("trace-1", "trace-2")
        key = self.create_personal_api_key_with_scopes(["llm_analytics:read"])
        self.client.logout()
        headers = {"authorization": f"Bearer {key}"}

        first = self.client.get(self._url(), {"limit": 1}, headers=headers)
        second = self.client.get(self._url(), {"limit": 1, "cursor": first.json()["nextCursor"]}, headers=headers)

        assert first.status_code == 200
        body = first.json()
        assert [(item["id"], item["distinctId"]) for item in body["items"]] == [("trace-2", "user-1")]
        assert body["counts"] == {"total": 2, "errors": 0, "feedback": 0}
        assert body["nextCursor"] is not None
        page = second.json()
        assert ([item["id"] for item in page["items"]], page["counts"], page["nextCursor"]) == (["trace-1"], None, None)

    def test_a_capped_row_says_its_totals_are_partial_and_names_no_default_step(self) -> None:
        for minutes in range(3):
            self.events.add("big", minutes=minutes)
        self.events.seed()

        with patch.object(trace_queries, "PAGE_ROW_CAP_PER_TRACE", 2):
            [item] = self._get().json()["items"]

        assert (item["totalsPartial"], item["defaultNodeId"]) == (True, None)

    def test_a_key_without_the_scope_is_refused(self) -> None:
        assert self._get(scopes=["query:read"]).status_code == 403

    @parameterized.expand(
        [
            ("read key", ["llm_analytics:read"], 403),
            ("read and query key", ["llm_analytics:read", "query:read"], 200),
            ("read key with query write, which covers read", ["llm_analytics:read", "query:write"], 200),
            ("browser session", None, 200),
        ]
    )
    def test_a_custom_expression_needs_the_query_scope(
        self, _name: str, scopes: list[str] | None, expected_status: int
    ) -> None:
        self.events.add("chosen", properties={"$ai_model": "gpt-test"})
        self.events.add("other", minutes=1, properties={"$ai_model": "gpt-other"})
        self.events.seed()

        response = self._get({"properties": CUSTOM_EXPRESSION}, scopes=scopes)

        assert response.status_code == expected_status
        if expected_status == 403:
            assert "query:read" in response.json()["detail"]
        else:
            assert [item["id"] for item in response.json()["items"]] == ["chosen"]

    @parameterized.expand(
        [
            ("bad cursor", {"cursor": "%%%"}),
            ("from after to", {"date_from": "2026-09-02", "date_to": "2026-09-01"}),
            ("unparsable date", {"date_from": "last tuesday"}),
            ("unparsable filters", {"properties": "{"}),
            ("custom expression that does not parse", {"properties": json.dumps([{"type": "hogql", "key": "1 ="}])}),
            ("group key alone", {"group_key": "acme"}),
            ("group type alone", {"group_type_index": 0}),
            ("group type out of range", {"group_key": "acme", "group_type_index": 5}),
            ("limit too large", {"limit": 101}),
            ("limit too small", {"limit": 0}),
            ("unknown view", {"view": "slow"}),
            ("person id that is not a uuid", {"person_id": "not-a-uuid"}),
            (
                "custom expression that fails in clickhouse",
                {"properties": json.dumps([{"type": "hogql", "key": "toDateTime('not a date') > now()"}])},
            ),
        ]
    )
    def test_bad_input_is_a_400(self, _name: str, params: dict[str, str | int]) -> None:
        assert self._get(params).status_code == 400

    @parameterized.expand(
        [
            ("properties", {"properties": json.dumps([{"type": "event", "key": "plan", "value": "pro"}])}),
            ("search", {"search": "invoice"}),
            ("blank search", {"search": ""}),
            ("view", {"view": "errors"}),
            ("person", {"person_id": "00000000-0000-4000-8000-0000000000aa"}),
            ("group", {"group_key": "acme", "group_type_index": 1}),
            ("test accounts on", {"filter_test_accounts": "true"}),
            ("test accounts off", {"filter_test_accounts": "false"}),
        ]
    )
    def test_session_scope_rejects_list_filters(self, _name: str, params: dict[str, str | int]) -> None:
        response = self._get({"session_id": "session-a", **params})

        assert (response.status_code, response.json()) == (
            400,
            {"detail": "A session reads on its own. Remove the list filters."},
        )

    @parameterized.expand(
        [
            ("session", {"session_id": "session-a", "around": "elsewhere"}, "The trace is not in this session."),
            ("list", {"around": "elsewhere"}, "The trace is not in this list."),
        ]
    )
    def test_around_unknown_trace_is_400(self, _name: str, params: dict[str, str | int], detail: str) -> None:
        self.events.add("inside", properties={"$ai_session_id": "session-a"})
        self.events.add("elsewhere", minutes=1, properties={"$ai_session_id": "session-b"})
        self.events.seed()

        response = self._get(params if "session_id" in params else {**params, "view": "errors"})

        assert (response.status_code, response.json()) == (400, {"detail": detail})

    def test_a_session_reads_oldest_first_around_a_trace_and_both_ways(self) -> None:
        for index in range(6):
            self.events.add(f"t{index}", minutes=index, properties={"$ai_session_id": "session-a"})
        self.events.seed()
        session = {"session_id": "session-a", "order": "oldest_first"}

        around = self._get({**session, "around": "t3", "limit": 2}).json()
        previous = self._get({**session, "before_cursor": around["previousCursor"], "limit": 2}).json()
        following = self._get({**session, "cursor": around["nextCursor"], "limit": 2}).json()

        assert [[item["id"] for item in page["items"]] for page in (around, previous, following)] == [
            ["t2", "t3"],
            ["t0", "t1"],
            ["t4", "t5"],
        ]
        assert (around["counts"], previous["previousCursor"], following["nextCursor"]) == (None, None, None)

    @parameterized.expand(
        [
            ("cursor and before cursor", {"cursor": "a", "before_cursor": "b"}),
            ("cursor and around", {"cursor": "a", "around": "t"}),
            ("before cursor and around", {"before_cursor": "b", "around": "t"}),
            ("unknown order", {"order": "sideways"}),
        ]
    )
    def test_conflicting_paging_is_a_400(self, _name: str, params: dict[str, str | int]) -> None:
        assert self._get(params).status_code == 400

    @parameterized.expand(
        [
            (
                "metric attribute filter",
                [{"type": "metric_attribute", "key": "x", "value": "y", "operator": "exact"}],
                "Filters of type metric_attribute don't apply to traces. Remove them.",
            ),
            (
                "feature flag filter",
                [{"type": "flag", "key": "1", "value": True, "operator": "flag_evaluates_to"}],
                "Filters of type flag don't apply to traces. Remove them.",
            ),
            (
                "warehouse person filter without a table",
                [{"type": "data_warehouse_person_property", "key": "plan", "value": "pro", "operator": "exact"}],
                "A data warehouse person property filter needs a key of the form table.property, with one dot.",
            ),
            (
                "too many filters",
                [{"type": "event", "key": "plan", "value": "pro"}] * 51,
                "Send at most 50 property filters.",
            ),
            (
                "group filter without a group type",
                [{"type": "group", "key": "industry", "value": "retail", "operator": "exact"}],
                "A group property filter needs a group type index.",
            ),
            (
                "element filter that has no query",
                [{"type": "element", "key": "selector", "value": "button", "operator": "icontains"}],
                "One of the property filters can't be applied to traces. Change its operator or remove it.",
            ),
        ]
    )
    def test_a_filter_the_selection_rejects_is_a_400_with_its_reason(
        self, _name: str, filters: list[dict[str, object]], reason: str
    ) -> None:
        response = self._get({"properties": json.dumps(filters)})

        assert (response.status_code, response.json()) == (400, {"detail": reason})

    @parameterized.expand(
        [
            ("quick filter", {"view": "errors"}, ["errored"]),
            ("search", {"search": "  invoice  "}, ["searched"]),
            ("blank search", {"search": "  "}, ["grouped", "searched", "errored", "personal"]),
            ("person", {"person_id": "00000000-0000-4000-8000-0000000000aa"}, ["personal"]),
            ("group", {"group_key": "acme", "group_type_index": 1}, ["grouped"]),
            (
                "event property",
                {"properties": json.dumps([{"type": "event", "key": "plan", "value": "pro"}])},
                ["errored"],
            ),
        ]
    )
    def test_each_param_narrows_the_list(self, _name: str, params: dict[str, str | int], expected: list[str]) -> None:
        self.events.add("personal", person_id="00000000-0000-4000-8000-0000000000aa")
        self.events.add("errored", minutes=1, properties={"$ai_is_error": True, "plan": "pro"})
        self.events.add("searched", minutes=2, properties={"$ai_input": [{"role": "user", "content": "My invoice"}]})
        self.events.add("grouped", minutes=3, properties={"$group_1": "acme"})
        self.events.seed()

        assert self._listed(params) == expected

    @parameterized.expand(
        [
            ("project default on", True, {}, ["customer"]),
            ("project default off", False, {}, ["internal", "customer"]),
            ("project default unset", None, {}, ["internal", "customer"]),
            ("project default overridden", True, {"filter_test_accounts": "false"}, ["internal", "customer"]),
        ]
    )
    def test_test_accounts_follow_the_project_default(
        self, _name: str, default_checked: bool | None, params: dict[str, str | int], expected: list[str]
    ) -> None:
        self.team.test_account_filters = [
            {"key": "account", "value": "internal", "operator": "is_not", "type": "event"}
        ]
        self.team.test_account_filters_default_checked = default_checked
        self.team.save()
        self.events.add("customer", properties={"account": "customer"})
        self.events.add("internal", minutes=1, properties={"account": "internal"})
        self.events.seed()

        assert self._listed(params) == expected

    @parameterized.expand(
        [
            ("customer session", "session", False, ["customer"]),
            ("impersonated session", "session", True, ["support", "customer"]),
            ("customer oauth token", "oauth", False, ["customer"]),
            ("oauth token minted while impersonating", "oauth", True, ["support", "customer"]),
        ]
    )
    def test_support_traces_show_only_to_an_impersonating_caller(
        self, _name: str, credential: str, impersonated: bool, expected: list[str]
    ) -> None:
        headers: dict[str, str] = {}
        if credential == "oauth":
            staff = User.objects.create_and_join(self.organization, "staff@example.com", None) if impersonated else None
            headers["authorization"] = f"Bearer {self._oauth_token(impersonated_by=staff)}"
            self.client.logout()
        elif impersonated:
            session = self.client.session
            session[loginas_settings.USER_SESSION_FLAG] = "staff-user"
            session.save()
        self.events.add("customer")
        self.events.add("support", minutes=1, properties={"ai_support_impersonated": True})
        self.events.seed()

        response = self.client.get(self._url(), headers=headers)

        assert [item["id"] for item in response.json()["items"]] == expected

    def _oauth_token(self, *, impersonated_by: User | None) -> str:
        application = OAuthApplication.objects.create(
            name="Example app",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token="pha_example_list_token",
            expires=timezone.now() + timedelta(hours=1),
            scope="llm_analytics:read",
            impersonated_by=impersonated_by,
        )
        return token.token

    @parameterized.expand([("visible", False, ["chosen"]), ("restricted for the viewer", True, [])])
    def test_a_restricted_property_filter_does_not_leak(
        self, _name: str, restricted: bool, expected: list[str]
    ) -> None:
        if restricted:
            restrict_property(self, "plan")
        self.events.add("chosen", properties={"plan": "enterprise"})
        self.events.add("other", minutes=1, properties={"plan": "free"})
        self.events.seed()

        response = self._get({"properties": json.dumps([{"type": "event", "key": "plan", "value": "enterprise"}])})

        assert [item["id"] for item in response.json()["items"]] == expected
        assert response.json()["counts"]["total"] == len(expected)

    @parameterized.expand(
        [("browser session", None, "app_per_org"), ("personal api key", ["llm_analytics:read"], "api_per_team")]
    )
    def test_a_full_query_slot_is_a_429(self, _name: str, scopes: list[str] | None, exhausted_limit: str) -> None:
        def use(limiter: RateLimit, *args: object, **kwargs: object) -> ConcurrencySlot | None:
            if limiter.limit_name == exhausted_limit:
                raise ConcurrencyLimitExceeded(exhausted_limit)
            return None

        with (
            patch("posthog.clickhouse.client.limit.TEST", False),
            patch.object(RateLimit, "use", autospec=True, side_effect=use),
        ):
            response = self._get(scopes=scopes)

        assert response.status_code == 429
        assert response["Retry-After"] == str(CONCURRENCY_LIMIT_RETRY_AFTER_SECONDS)

    def test_a_page_is_built_after_its_query_slot_is_released(self) -> None:
        self.events.seed_traces("trace-1")

        with QuerySlotRecorder().recording("load_trace_list") as recorder:
            response = self._get()

        assert (response.status_code, recorder.loaded_while_holding, recorder.built_while_holding) == (
            200,
            [True],
            [False],
        )

    def test_the_two_reads_match_their_snapshots(self) -> None:
        self.events.add("trace-1", properties={"plan": "pro"})
        self.events.seed()

        with self.capture_select_queries() as queries:
            response = self._get(
                {"properties": json.dumps([{"type": "event", "key": "plan", "value": "pro"}])},
                scopes=["llm_analytics:read"],
            )

        assert response.status_code == 200
        reads = [query for query in queries if "FROM system.columns" not in query]
        assert len(reads) == 2
        for query in reads:
            self.assertQueryMatchesSnapshot(query)
