import json
from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from .trace_fixtures import T0, QuerySlotRecorder, TraceEvents, encode_segment

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

CUSTOM_EXPRESSION = json.dumps([{"type": "hogql", "key": "properties.$ai_model = 'gpt-test'"}])
UNSAFE_SESSION_ID = "a/b%c ü"
CHAT: dict[str, object] = {
    "$ai_session_id": "session-a",
    "$ai_input": [{"role": "user", "content": "Where is my parcel?"}],
    "$ai_output_choices": [{"role": "assistant", "content": "On its way."}],
}


@time_machine.travel(T0 + timedelta(days=1), tick=False)
class TestSessionViewSet(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.events = TraceEvents(self.team)

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/ai_observability/sessions/{suffix}"

    def _get(
        self, url: str, params: Mapping[str, str | int] | None = None, *, scopes: list[str] | None = None
    ) -> "_MonkeyPatchedResponse":
        headers = {}
        if scopes is not None:
            headers["authorization"] = f"Bearer {self.create_personal_api_key_with_scopes(scopes)}"
            self.client.logout()
        return self.client.get(url, params, headers=headers)

    def test_list_pages_sessions_with_facts(self) -> None:
        self.events.add("a1", minutes=0, properties={"$ai_session_id": "session-a", "$ai_latency": 2})
        self.events.add("a2", minutes=1, properties={"$ai_session_id": "session-a", "$ai_latency": 3})
        self.events.add("b1", minutes=2, properties={"$ai_session_id": "session-b"})
        self.events.seed()

        first = self._get(self._url(), {"limit": 1}).json()
        second = self._get(self._url(), {"limit": 1, "cursor": first["nextCursor"]}).json()

        assert [item["id"] for item in first["items"]] == ["session-b"]
        assert [item["id"] for item in second["items"]] == ["session-a"]
        assert second["nextCursor"] is None
        assert second["items"][0]["turnCount"] == 2
        assert second["items"][0]["totals"]["latencyMs"] == 5000
        assert second["items"][0]["erroredTurns"] == 0
        assert second["items"][0]["firstTraceId"] == "a1"

    def test_list_rejects_query_scoped_filters_without_query_scope(self) -> None:
        self.events.add("a1", properties={"$ai_session_id": "session-a", "$ai_model": "gpt-test"})
        self.events.seed()

        denied = self._get(self._url(), {"properties": CUSTOM_EXPRESSION}, scopes=["llm_analytics:read"])
        allowed = self._get(self._url(), {"properties": CUSTOM_EXPRESSION}, scopes=["llm_analytics:read", "query:read"])

        assert denied.status_code == 403
        assert "query:read" in denied.json()["detail"]
        assert [item["id"] for item in allowed.json()["items"]] == ["session-a"]

    @parameterized.expand(
        [
            ("bad cursor", {"cursor": "%%%"}),
            ("from after to", {"date_from": "2026-09-02", "date_to": "2026-09-01"}),
            ("group key alone", {"group_key": "acme"}),
            ("limit too large", {"limit": 101}),
        ]
    )
    def test_list_bad_input_is_a_400(self, _name: str, params: dict[str, str | int]) -> None:
        assert self._get(self._url(), params).status_code == 400

    def test_personal_api_key_with_read_scope_can_list(self) -> None:
        self.events.add("a1", properties={"$ai_session_id": "session-a"})
        self.events.seed()

        response = self._get(self._url(), scopes=["llm_analytics:read"])

        assert response.status_code == 200
        assert [item["id"] for item in response.json()["items"]] == ["session-a"]

    def test_retrieve_round_trips_unsafe_session_id(self) -> None:
        self.events.add("a1", properties={"$ai_session_id": UNSAFE_SESSION_ID})
        self.events.seed()

        response = self._get(self._url(encode_segment(UNSAFE_SESSION_ID) + "/"))

        assert response.status_code == 200
        assert response.json()["id"] == UNSAFE_SESSION_ID

    def test_retrieve_unknown_is_404(self) -> None:
        assert self._get(self._url(encode_segment("missing") + "/")).status_code == 404

    @parameterized.expand(
        [
            ("malformed id", "not base64!", {}),
            ("malformed timestamp", None, {"timestamp": "yesterday"}),
        ]
    )
    def test_retrieve_malformed_input_is_a_400(self, _name: str, segment: str | None, params: dict[str, str]) -> None:
        url = self._url((segment or encode_segment("session-a")) + "/")

        assert self._get(url, params).status_code == 400

    def test_retrieve_old_session_needs_timestamp(self) -> None:
        self.events.add("a1", properties={"$ai_session_id": "session-a"})
        self.events.seed(aged_out={"a1"})
        url = self._url(encode_segment("session-a") + "/")

        assert self._get(url).status_code == 404
        hinted = self._get(url, {"timestamp": T0.isoformat()})
        assert hinted.status_code == 200
        assert hinted.json()["firstTraceId"] == "a1"

    def _turns_url(self, session_id: str = "session-a") -> str:
        return self._url(f"{encode_segment(session_id)}/turns/")

    def test_personal_api_key_with_read_scope_can_read_turns(self) -> None:
        self.events.add("a1", properties=CHAT)
        self.events.add("a2", minutes=1, properties=CHAT)
        self.events.seed()

        response = self._get(self._turns_url(), {"limit": 1}, scopes=["llm_analytics:read"])

        assert response.status_code == 200
        body = response.json()
        (turn,) = body["items"]
        assert (turn["id"], turn["sessionId"], turn["outputMissingReason"]) == ("a1", "session-a", None)
        assert turn["input"]["messages"][-1]["parts"][0]["text"] == "Where is my parcel?"
        assert turn["output"]["messages"][-1]["parts"][0]["text"] == "On its way."
        assert (body["previousCursor"], body["nextCursor"] is not None) == (None, True)

    def test_turns_unknown_session_is_404(self) -> None:
        assert self._get(self._turns_url("missing")).status_code == 404

    def test_turns_reads_inside_query_slot_and_builds_after(self) -> None:
        self.events.add("a1", properties=CHAT)
        self.events.seed()

        with QuerySlotRecorder().recording("load_session_turns") as recorder:
            response = self._get(self._turns_url())

        assert (response.status_code, recorder.loaded_while_holding, recorder.built_while_holding) == (
            200,
            [True],
            [False],
        )

    def test_turns_old_session_needs_timestamp(self) -> None:
        self.events.add("a1", properties={"$ai_session_id": "session-a"})
        self.events.seed(aged_out={"a1"})

        assert self._get(self._turns_url()).status_code == 404
        hinted = self._get(self._turns_url(), {"timestamp": T0.isoformat()})
        assert [turn["id"] for turn in hinted.json()["items"]] == ["a1"]

    @parameterized.expand(
        [
            ("two paging params", {"cursor": "abc", "around": "a1"}),
            ("bad cursor", {"cursor": "%%%"}),
            ("limit too large", {"limit": 21}),
        ]
    )
    def test_turns_bad_input_is_a_400(self, _name: str, params: dict[str, str | int]) -> None:
        self.events.add("a1", properties=CHAT)
        self.events.seed()

        assert self._get(self._turns_url(), params).status_code == 400
