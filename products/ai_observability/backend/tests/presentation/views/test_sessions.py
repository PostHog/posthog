import json
from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.ai_observability.backend.facade import api
from products.ai_observability.backend.presentation.views.session_page import SessionPageRequestSerializer
from products.ai_observability.backend.presentation.views.session_turns import SessionTurnsQuerySerializer
from products.ai_observability.backend.presentation.views.sessions import SessionListQuerySerializer
from products.ai_observability.backend.presentation.views.trace_ids import (
    UnreadableSessionIdError,
    decode_session_id_segment,
)

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
READ_KEY = ["llm_analytics:read"]


@time_machine.travel(T0 + timedelta(days=1), tick=False)
class TestSessionViewSet(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.events = TraceEvents(self.team)

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/ai_observability/sessions/{suffix}"

    def _headers(self, scopes: list[str] | None) -> dict[str, str]:
        if scopes is None:
            return {}
        self.client.logout()
        return {"authorization": f"Bearer {self.create_personal_api_key_with_scopes(scopes)}"}

    def _get(
        self, url: str, params: Mapping[str, str | int] | None = None, *, scopes: list[str] | None = None
    ) -> "_MonkeyPatchedResponse":
        return self.client.get(url, params, headers=self._headers(scopes))

    def _post(
        self, read: str, body: Mapping[str, object], *, scopes: list[str] | None = None
    ) -> "_MonkeyPatchedResponse":
        return self.client.post(self._url(f"{read}/"), body, format="json", headers=self._headers(scopes))

    def test_a_read_key_lists_sessions_with_their_facts(self) -> None:
        self.events.add("a1", properties={"$ai_session_id": "session-a", "$ai_latency": 2})
        self.events.seed()

        response = self._get(self._url(), scopes=READ_KEY)

        assert (response.status_code, [item["id"] for item in response.json()["items"]]) == (200, ["session-a"])

    def test_list_rejects_query_scoped_filters_without_query_scope(self) -> None:
        self.events.add("a1", properties={"$ai_session_id": "session-a", "$ai_model": "gpt-test"})
        self.events.seed()

        denied = self._get(self._url(), {"properties": CUSTOM_EXPRESSION}, scopes=READ_KEY)
        allowed = self._get(self._url(), {"properties": CUSTOM_EXPRESSION}, scopes=[*READ_KEY, "query:read"])

        assert denied.status_code == 403
        assert "query:read" in denied.json()["detail"]
        assert [item["id"] for item in allowed.json()["items"]] == ["session-a"]

    def test_list_bad_cursor_is_a_400(self) -> None:
        assert self._get(self._url(), {"cursor": "%%%"}).status_code == 400

    def test_retrieve_round_trips_unsafe_session_id(self) -> None:
        self.events.add("a1", properties={"$ai_session_id": UNSAFE_SESSION_ID})
        self.events.seed()

        response = self._get(self._url(encode_segment(UNSAFE_SESSION_ID) + "/"), scopes=READ_KEY)

        assert (response.status_code, response.json()["id"]) == (200, UNSAFE_SESSION_ID)

    def test_retrieve_unknown_is_404(self) -> None:
        assert self._get(self._url(encode_segment("missing") + "/")).status_code == 404

    @parameterized.expand([("retrieve", "/"), ("turns", "/turns/")])
    def test_a_malformed_session_id_is_a_400(self, _name: str, suffix: str) -> None:
        assert self._get(self._url("not base64!" + suffix)).status_code == 400

    def _turns_url(self, session_id: str = "session-a") -> str:
        return self._url(f"{encode_segment(session_id)}/turns/")

    def test_a_read_key_reads_turns(self) -> None:
        self.events.add("a1", properties=CHAT)
        self.events.add("a2", minutes=1, properties=CHAT)
        self.events.seed()

        response = self._get(self._turns_url(), {"limit": 1}, scopes=READ_KEY)

        assert (response.status_code, [item["id"] for item in response.json()["items"]]) == (200, ["a1"])

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

    def test_turns_bad_cursor_is_a_400(self) -> None:
        self.events.add("a1", properties=CHAT)
        self.events.seed()

        assert self._get(self._turns_url(), {"cursor": "%%%"}).status_code == 400

    @parameterized.expand([("previews",), ("people",)])
    def test_a_read_key_reads_a_page_of_sessions_by_id(self, read: str) -> None:
        self.events.add("a1", properties=CHAT)
        self.events.seed()

        response = self._post(read, {"session_ids": ["session-a", "missing"]}, scopes=READ_KEY)

        assert (response.status_code, [item["sessionId"] for item in response.json()["items"]]) == (
            200,
            ["session-a", "missing"],
        )

    @parameterized.expand(
        [
            (f"{read} {name}", read, body, scopes, status)
            for read in ("previews", "people")
            for name, body, scopes, status in [
                ("without the read scope", {"session_ids": ["session-a"]}, ["query:read"], 403),
                ("without session ids", {"session_ids": []}, None, 400),
            ]
        ]
    )
    def test_titles_and_people_refuse_a_bad_request(
        self, _name: str, read: str, body: dict[str, object], scopes: list[str] | None, status: int
    ) -> None:
        assert self._post(read, body, scopes=scopes).status_code == status

    @parameterized.expand([("turns",), ("previews",), ("people",)])
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch(
        "products.ai_observability.backend.presentation.views.trace_page.ConversationReadBurstThrottle.rate",
        new="1/minute",
    )
    def test_throttles_a_browser_session_past_its_budget(self, read: str, _rate_limit: MagicMock) -> None:
        def request() -> int:
            if read == "turns":
                return self._get(self._turns_url("missing")).status_code
            return self._post(read, {"session_ids": ["missing"]}).status_code

        assert [request(), request()][1] == 429


class TestSessionRequestParsing(SimpleTestCase):
    def test_sessions_list_accepts_the_person_scope_only(self) -> None:
        fields = SessionListQuerySerializer().fields

        assert "person_id" in fields
        assert not {"error", "tool", "failed_tool"} & set(fields)

    @parameterized.expand(
        [
            ("a dot", ".", True),
            ("two dots", "..", True),
            ("an id at the length cap", "s" * api.SESSION_ID_MAX_LENGTH, True),
            ("an id over the length cap", "s" * (api.SESSION_ID_MAX_LENGTH + 1), False),
        ]
    )
    def test_a_session_id_segment_reads_every_id_the_list_hands_out(
        self, _name: str, session_id: str, readable: bool
    ) -> None:
        try:
            decoded: str | None = decode_session_id_segment(encode_segment(session_id))
        except UnreadableSessionIdError:
            decoded = None

        assert decoded == (session_id if readable else None)

    @parameterized.expand(
        [
            ("malformed timestamp hint", {"timestamp_hint": "yesterday"}),
            ("two paging params", {"cursor": "abc", "around": "a1"}),
            ("an anchor too long to be a trace id", {"around": "t" * 1001}),
            ("too many turns", {"limit": api.SESSION_TURNS_PAGE_SIZE + 1}),
        ]
    )
    def test_turns_refuse_unreadable_params(self, _name: str, params: dict[str, str | int]) -> None:
        assert not SessionTurnsQuerySerializer(data=params).is_valid()

    def test_turns_keep_the_spaces_of_an_anchor_trace_id(self) -> None:
        serializer = SessionTurnsQuerySerializer(data={"around": " t1 "})

        assert serializer.is_valid() and serializer.validated_data["around"] == " t1 "

    @parameterized.expand(
        [
            ("too many session ids", [f"s-{index}" for index in range(api.SESSION_LIST_MAX_LIMIT + 1)]),
            ("a session id longer than any listed", ["s" * (api.SESSION_ID_MAX_LENGTH + 1)]),
        ]
    )
    def test_a_page_of_sessions_refuses_ids_the_list_never_hands_out(self, _name: str, session_ids: list[str]) -> None:
        assert not SessionPageRequestSerializer(data={"session_ids": session_ids}).is_valid()
