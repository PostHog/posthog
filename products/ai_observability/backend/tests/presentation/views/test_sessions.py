import json
from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized

from products.ai_observability.backend.facade import api
from products.ai_observability.backend.presentation.views.trace_ids import (
    UnreadableSessionIdError,
    decode_session_id_segment,
)

from .trace_fixtures import T0, TraceEvents, encode_segment

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

CUSTOM_EXPRESSION = json.dumps([{"type": "hogql", "key": "properties.$ai_model = 'gpt-test'"}])
UNSAFE_SESSION_ID = "a/b%c ü"
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

    @parameterized.expand([("retrieve", "/")])
    def test_a_malformed_session_id_is_a_400(self, _name: str, suffix: str) -> None:
        assert self._get(self._url("not base64!" + suffix)).status_code == 400


class TestSessionRequestParsing(SimpleTestCase):
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
