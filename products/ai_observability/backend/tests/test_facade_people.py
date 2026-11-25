from collections.abc import Callable
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import EventPropertyFilter, PropertyOperator

from posthog.paging import PageRequest
from posthog.test.persons import create_person

from products.ai_observability.backend.facade.contracts import TracePerson
from products.ai_observability.backend.facade.people import (
    LOOKBACK,
    PeopleOrder,
    PeopleQuery,
    get_person,
    load_people_first_seen,
    load_people_list,
    load_people_new_count,
)
from products.ai_observability.backend.facade.people_contracts import (
    PeopleNewCount,
    PersonFirstSeen,
    PersonFirstSeenList,
    PersonListCounts,
    PersonListItem,
    PersonPage,
)

from .logic.people.test_people_queries import CAROL, DAVE, ERIN, anonymous_root, generation
from .logic.traces.test_trace_selection_queries import at, seed, to_selection


class TestPeopleList(ClickhouseTestMixin, BaseTest):
    def _list_builder(self, *, include_anonymous: bool = False, **selection: Any) -> Callable[[], PersonPage]:
        people_query = PeopleQuery(
            selection=to_selection(self.team, {"date_from": -60, "date_to": 60, **selection}),
            order=PeopleOrder.LAST_SEEN,
            include_anonymous=include_anonymous,
            new_only=False,
            person_search=None,
        )
        return load_people_list(self.team, self.user, people_query, PageRequest(limit=50))

    def _list(self, *, include_anonymous: bool = False, **selection: Any) -> PersonPage:
        return self._list_builder(include_anonymous=include_anonymous, **selection)()

    def test_lists_people_with_labels_and_counts_from_their_own_events(self) -> None:
        create_person(
            team=self.team, uuid=CAROL, distinct_ids=["user-carol"], properties={"email": "carol@example.com"}
        )
        create_person(team=self.team, uuid=DAVE, distinct_ids=["user-dave"])
        seed(
            self.team,
            [
                generation("t-dave", 1, "user-dave"),
                anonymous_root("t-carol", 2),
                generation("t-carol", 3, "user-carol", **{"$ai_total_cost_usd": 0.5, "$ai_session_id": "s-1"}),
            ],
        )

        built = self._list()

        assert (built.count, [item.person.label for item in built.results]) == (2, ["carol@example.com", "user-dave"])
        assert built.results[0] == PersonListItem(
            id=CAROL,
            person=TracePerson(distinct_id="user-carol", label="carol@example.com"),
            anonymous=False,
            session_count=1,
            trace_count=1,
            cost=0.5,
            first_seen_in_range=at(3),
            last_seen=at(3),
        )
        assert (built.counts, built.needs_identification) == (PersonListCounts(anonymous=1), False)

    def test_a_person_is_shown_by_their_identified_distinct_id(self) -> None:
        create_person(
            team=self.team,
            uuid=CAROL,
            distinct_ids=["t-before-identify", "user-carol"],
            properties={"email": "carol@example.com"},
        )
        seed(self.team, [generation("t-after-identify", 1, "user-carol"), anonymous_root("t-before-identify", 2)])

        [item] = self._list().results

        assert item.person == TracePerson(distinct_id="user-carol", label="carol@example.com")

    def test_a_person_anonymous_in_the_selection_shows_their_anonymous_id(self) -> None:
        create_person(
            team=self.team,
            uuid=CAROL,
            distinct_ids=["t-before-identify", "user-carol"],
            properties={"email": "carol@example.com"},
        )
        seed(
            self.team,
            [
                {**anonymous_root("t-before-identify", 1), "properties": {"flavour": "mint"}},
                generation("t-after-identify", 2, "user-carol"),
            ],
        )
        mint = EventPropertyFilter(key="flavour", value="mint", operator=PropertyOperator.EXACT)

        [item] = self._list(include_anonymous=True, properties=[mint.model_dump()]).results

        assert (item.anonymous, item.person) == (
            True,
            TracePerson(distinct_id="t-before-identify", label="Anonymous t-before"),
        )

    def test_a_page_is_two_reads(self) -> None:
        create_person(
            team=self.team, uuid=CAROL, distinct_ids=["user-carol"], properties={"email": "carol@example.com"}
        )
        seed(self.team, [generation("t-carol", 1, "user-carol")])
        # A read can also refresh the cached column metadata, which is not part of a page, so a warm read goes first.
        self._list()

        with self.capture_select_queries() as queries:
            build = self._list_builder()

        assert (len(queries), [item.person.label for item in build().results]) == (2, ["carol@example.com"])

    def test_a_person_with_no_person_profile_is_labeled_by_their_distinct_id(self) -> None:
        seed(
            self.team,
            [{**generation("t-erin", 1, "user-erin", **{"$process_person_profile": False}), "person_id": ERIN}],
        )

        [item] = self._list().results

        assert (item.id, item.person) == (ERIN, TracePerson(distinct_id="user-erin", label="user-erin"))

    @parameterized.expand([("switch off", False, [], True), ("switch on", True, ["Anonymous t-1"], False)])
    def test_only_anonymous_people_need_identification(
        self, _name: str, include_anonymous: bool, labels: list[str], needs_identification: bool
    ) -> None:
        seed(self.team, [anonymous_root("t-1", 1)])

        built = self._list(include_anonymous=include_anonymous)

        assert ([item.person.label for item in built.results], built.needs_identification) == (
            labels,
            needs_identification,
        )


class TestPerson(ClickhouseTestMixin, BaseTest):
    def test_reads_one_person_from_their_own_events_or_none(self) -> None:
        create_person(
            team=self.team, uuid=CAROL, distinct_ids=["user-carol"], properties={"email": "carol@example.com"}
        )
        create_person(team=self.team, uuid=DAVE, distinct_ids=["user-dave"])
        seed(
            self.team,
            [
                generation("t-carol-before", -10 * 24 * 60, "user-carol"),
                generation("t-shared", 1, "user-dave"),
                generation("t-shared", 2, "user-carol", **{"$ai_total_cost_usd": 0.5}),
            ],
        )
        selection = to_selection(self.team, {"date_from": -60, "date_to": 60})

        assert get_person(self.team, self.user, selection, CAROL) == PersonListItem(
            id=CAROL,
            person=TracePerson(distinct_id="user-carol", label="carol@example.com"),
            anonymous=False,
            session_count=0,
            trace_count=1,
            cost=0.5,
            first_seen_in_range=at(2),
            last_seen=at(2),
        )
        assert get_person(self.team, self.user, selection, ERIN) is None


class TestPeopleNewCount(ClickhouseTestMixin, BaseTest):
    def test_counts_the_listed_people_with_no_activity_in_the_lookback(self) -> None:
        create_person(team=self.team, uuid=CAROL, distinct_ids=["user-carol"])
        create_person(team=self.team, uuid=DAVE, distinct_ids=["user-dave"])
        seed(
            self.team,
            [
                generation("t-carol-before", -10 * 24 * 60, "user-carol"),
                generation("t-carol", 1, "user-carol"),
                generation("t-dave", 2, "user-dave"),
                anonymous_root("t-anonymous", 3),
            ],
        )
        selection = to_selection(self.team, {"date_from": -60, "date_to": 60})

        assert load_people_new_count(
            self.team, self.user, selection, include_anonymous=False, person_search=None
        ) == PeopleNewCount(count=1)


class TestPeopleFirstSeen(ClickhouseTestMixin, BaseTest):
    def test_lists_each_requested_id_once_in_request_order_with_the_bound(self) -> None:
        create_person(team=self.team, uuid=CAROL, distinct_ids=["user-carol"])
        create_person(team=self.team, uuid=DAVE, distinct_ids=["user-dave"])
        seed(
            self.team,
            [generation("t-dave", -10 * 24 * 60, "user-dave"), generation("t-carol", 5, "user-carol")],
        )
        selection = to_selection(self.team, {"date_from": 0, "date_to": 60})

        built = load_people_first_seen(self.team, self.user, selection, [DAVE, ERIN, CAROL, DAVE])

        assert built == PersonFirstSeenList(
            items=[
                PersonFirstSeen(person_id=DAVE, first_seen=at(-10 * 24 * 60), is_new=False),
                PersonFirstSeen(person_id=ERIN, first_seen=None, is_new=True),
                PersonFirstSeen(person_id=CAROL, first_seen=at(5), is_new=True),
            ],
            checked_from=(at(0) - LOOKBACK).astimezone(self.team.timezone_info).date(),
        )
