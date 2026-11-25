import json
from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.test.persons import create_person

from products.ai_observability.backend.facade import people
from products.ai_observability.backend.presentation.views.people import PeopleListQuerySerializer, PeoplePagination

from ...logic.people.test_people_queries import CAROL, DAVE, ERIN
from .trace_fixtures import T0, QuerySlotRecorder, TraceEvents

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

CUSTOM_EXPRESSION = json.dumps([{"type": "hogql", "key": "properties.$ai_model = 'gpt-test'"}])
READ_KEY = ["llm_analytics:read"]


@time_machine.travel(T0 + timedelta(days=1), tick=False)
class TestPeopleViewSet(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.events = TraceEvents(self.team)
        create_person(
            team=self.team, uuid=CAROL, distinct_ids=["user-carol"], properties={"email": "carol@example.com"}
        )
        create_person(team=self.team, uuid=DAVE, distinct_ids=["user-dave"])

    def _get(
        self, params: Mapping[str, str | int] | None = None, *, scopes: list[str] | None = None
    ) -> "_MonkeyPatchedResponse":
        headers = {}
        if scopes is not None:
            self.client.logout()
            headers = {"authorization": f"Bearer {self.create_personal_api_key_with_scopes(scopes)}"}
        return self.client.get(f"/api/projects/{self.team.id}/ai_observability/people/", params, headers=headers)

    def _seed_carol_and_dave(self, **carol_properties: object) -> None:
        self.events.add("t-dave", distinct_id="user-dave", person_id=DAVE)
        self.events.add("t-carol", minutes=1, distinct_id="user-carol", person_id=CAROL, properties=carol_properties)
        self.events.seed()

    def _labels(self, response: "_MonkeyPatchedResponse") -> list[str]:
        assert response.status_code == 200, response.json()
        return [item["person"]["label"] for item in response.json()["results"]]

    def test_a_read_key_lists_people_in_the_kit_shape(self) -> None:
        self._seed_carol_and_dave()

        body = self._get({"limit": 1}, scopes=READ_KEY).json()

        assert set(body) == {"count", "next", "previous", "results", "counts", "lookbackDays", "needsIdentification"}
        assert (body["count"], body["previous"], [item["id"] for item in body["results"]]) == (2, None, [CAROL])
        assert "offset=1" in body["next"]
        assert (body["counts"], body["lookbackDays"], body["needsIdentification"]) == (
            {"anonymous": 0},
            30,
            False,
        )

    def test_view_new_lists_and_a_read_key_counts_only_new_people(self) -> None:
        self.events.add("t-carol-before", minutes=-10 * 24 * 60, distinct_id="user-carol", person_id=CAROL)
        self._seed_carol_and_dave()

        response = self._get({"view": "new"})
        self.client.logout()
        new_count = self.client.get(
            f"/api/projects/{self.team.id}/ai_observability/people/new_count/",
            headers={"authorization": f"Bearer {self.create_personal_api_key_with_scopes(READ_KEY)}"},
        )

        assert (self._labels(response), response.json()["count"]) == (["user-dave"], 1)
        assert (new_count.status_code, new_count.json()) == (200, {"count": 1})

    @parameterized.expand(
        [
            ("content search is not a param", {"search": "nothing matches this"}, ["carol@example.com", "user-dave"]),
            ("person search narrows", {"person_search": "CAROL@"}, ["carol@example.com"]),
        ]
    )
    def test_searches_people_not_content(self, _name: str, params: dict[str, str], labels: list[str]) -> None:
        self._seed_carol_and_dave()

        assert self._labels(self._get(params)) == labels

    @parameterized.expand(
        [
            ("by cost", {"order": "cost"}, ["user-dave", "carol@example.com"]),
            (
                "with anonymous people",
                {"include_anonymous": "true"},
                ["Anonymous t-anon", "carol@example.com", "user-dave"],
            ),
        ]
    )
    def test_lists_in_the_requested_order_and_reach(
        self, _name: str, params: dict[str, str], labels: list[str]
    ) -> None:
        self.events.add("t-dave", distinct_id="user-dave", person_id=DAVE, properties={"$ai_total_cost_usd": 0.9})
        self.events.add(
            "t-carol", minutes=1, distinct_id="user-carol", person_id=CAROL, properties={"$ai_total_cost_usd": 0.1}
        )
        self.events.add("t-anon", minutes=2, distinct_id="t-anon", person_id=ERIN)
        self.events.seed()

        assert self._labels(self._get(params)) == labels

    @parameterized.expand(
        [
            ("a person in range", CAROL, 200, "carol@example.com"),
            ("a person with no trace in range", ERIN, 404, None),
        ]
    )
    def test_a_read_key_reads_one_person(self, _name: str, person_id: str, status: int, label: str | None) -> None:
        self._seed_carol_and_dave()
        self.client.logout()
        headers = {"authorization": f"Bearer {self.create_personal_api_key_with_scopes(READ_KEY)}"}

        response = self.client.get(
            f"/api/projects/{self.team.id}/ai_observability/people/{person_id}/", headers=headers
        )

        assert response.status_code == status
        assert (response.json()["person"]["label"] if status == 200 else None) == label

    def test_rejects_query_scoped_filters_without_query_scope(self) -> None:
        self._seed_carol_and_dave(**{"$ai_model": "gpt-test"})

        denied = self._get({"properties": CUSTOM_EXPRESSION}, scopes=READ_KEY)
        allowed = self._get({"properties": CUSTOM_EXPRESSION}, scopes=[*READ_KEY, "query:read"])

        assert denied.status_code == 403
        assert "query:read" in denied.json()["detail"]
        assert self._labels(allowed) == ["carol@example.com"]

    def test_rejects_an_unknown_order(self) -> None:
        assert self._get({"order": "traces"}).status_code == 400

    def test_reads_inside_the_query_slot_and_builds_after(self) -> None:
        self._seed_carol_and_dave()

        with QuerySlotRecorder().recording("load_people_list", facade=people) as recorder:
            response = self._get()

        assert (response.status_code, recorder.loaded_while_holding, recorder.built_while_holding) == (
            200,
            [True],
            [False],
        )


class TestPeopleRequestParsing(SimpleTestCase):
    @parameterized.expand(
        [
            ("an unknown view", {"view": "errors"}),
            ("a page over the maximum", {"limit": 101}),
            ("a negative offset", {"offset": -1}),
            ("an offset over the maximum", {"offset": 10_001}),
        ]
    )
    def test_refuses_unreadable_params(self, _name: str, params: dict[str, str | int]) -> None:
        assert not PeopleListQuerySerializer(data=params).is_valid()

    @parameterized.expand(
        [("to the last page the offset reaches", 9_950, True), ("past the offset maximum", 10_000, False)]
    )
    def test_links_the_next_page_only_within_the_offset_maximum(self, _name: str, offset: int, linked: bool) -> None:
        paginator = PeoplePagination()
        paginator.request = Request(APIRequestFactory().get("/people/", {"offset": offset}))
        paginator.offset, paginator.limit, paginator.count = offset, 50, 20_000

        assert (paginator.get_next_link() is not None) is linked
