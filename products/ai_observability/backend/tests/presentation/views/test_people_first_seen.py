from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.test.persons import create_person

from products.ai_observability.backend.presentation.views.people_first_seen import PeopleFirstSeenRequestSerializer

from ...logic.people.test_people_queries import CAROL, DAVE
from .trace_fixtures import T0, TraceEvents

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

READ_KEY = ["llm_analytics:read"]
RANGE = {"date_from": "-2d"}


@time_machine.travel(T0 + timedelta(days=1), tick=False)
class TestPeopleFirstSeenViewSet(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.events = TraceEvents(self.team)
        create_person(team=self.team, uuid=CAROL, distinct_ids=["user-carol"])
        create_person(team=self.team, uuid=DAVE, distinct_ids=["user-dave"])

    def _post(self, body: Mapping[str, object], *, scopes: list[str] | None = None) -> "_MonkeyPatchedResponse":
        headers = {}
        if scopes is not None:
            self.client.logout()
            headers = {"authorization": f"Bearer {self.create_personal_api_key_with_scopes(scopes)}"}
        return self.client.post(
            f"/api/projects/{self.team.id}/ai_observability/people/first_seen/", body, format="json", headers=headers
        )

    def test_a_read_key_gets_one_item_per_requested_id_in_order(self) -> None:
        self.events.add("t-carol-before", minutes=-5 * 24 * 60, distinct_id="user-carol", person_id=CAROL)
        self.events.add("t-carol", minutes=60, distinct_id="user-carol", person_id=CAROL)
        self.events.seed()

        response = self._post({"person_ids": [DAVE, CAROL, DAVE], **RANGE}, scopes=READ_KEY)

        body = response.json()
        assert response.status_code == 200, body
        assert [(item["personId"], item["firstSeen"] is not None) for item in body["items"]] == [
            (DAVE, False),
            (CAROL, True),
        ]
        assert body["items"][1]["firstSeen"].startswith((T0 - timedelta(days=5)).strftime("%Y-%m-%d"))
        assert "checkedFrom" in body

    @parameterized.expand(
        [
            ("no ids", {"person_ids": [], **RANGE}),
            ("too many ids", {"person_ids": [CAROL] * 101, **RANGE}),
            ("not a uuid", {"person_ids": ["user-carol"], **RANGE}),
            ("a bad date", {"person_ids": [CAROL], "date_from": "not a date"}),
            (
                "a range that ends before it starts",
                {"person_ids": [CAROL], "date_from": "2026-02-01", "date_to": "2026-01-01"},
            ),
        ]
    )
    def test_refuses_a_bad_request(self, _name: str, body: dict[str, object]) -> None:
        assert self._post(body).status_code == 400

    def test_refuses_a_key_without_the_read_scope(self) -> None:
        assert self._post({"person_ids": [CAROL], **RANGE}, scopes=["query:read"]).status_code == 403

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch(
        "products.ai_observability.backend.presentation.views.trace_page.ConversationReadBurstThrottle.rate",
        new="1/minute",
    )
    def test_throttles_a_browser_session_past_its_budget(self, _rate_limit: MagicMock) -> None:
        responses = [self._post({"person_ids": [CAROL], **RANGE}).status_code for _ in range(2)]

        assert responses[1] == 429


class TestPeopleFirstSeenRequestParsing(SimpleTestCase):
    def test_filter_test_accounts_defaults_to_the_projects_setting(self) -> None:
        serializer = PeopleFirstSeenRequestSerializer(data={"person_ids": [CAROL]})

        assert serializer.is_valid()
        assert serializer.validated_data["filter_test_accounts"] is None
