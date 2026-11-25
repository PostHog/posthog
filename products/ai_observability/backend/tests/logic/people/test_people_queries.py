import re
from collections.abc import Callable
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import EventPropertyFilter, PropertyOperator

from posthog.hogql.constants import HogQLGlobalSettings

from posthog.models import Organization, Team
from posthog.paging import PageRequest
from posthog.test.persons import create_person

from products.ai_observability.backend.logic.people.people import PeopleCounts, PeopleOrder, PeopleQuery
from products.ai_observability.backend.logic.people.people_queries import (
    PeoplePageRows,
    PersonFirstSeenRow,
    load_new_people_count,
    load_people_first_seen,
    load_people_page,
)

from ..traces.test_trace_selection_queries import at, seed, to_selection

CAROL, DAVE, ERIN = (
    "00000000-0000-4000-8000-00000000000c",
    "00000000-0000-4000-8000-00000000000d",
    "00000000-0000-4000-8000-00000000000e",
)
DAYS = 24 * 60
WINDOW = {"date_from": -60, "date_to": 60}


def generation(trace_id: str, minutes: int, distinct_id: str, **properties: Any) -> dict[str, Any]:
    return {
        "event": "$ai_generation",
        "trace_id": trace_id,
        "minutes": minutes,
        "distinct_id": distinct_id,
        "properties": properties,
    }


def anonymous_root(trace_id: str, minutes: int) -> dict[str, Any]:
    return {"event": "$ai_trace", "trace_id": trace_id, "minutes": minutes, "distinct_id": trace_id}


class TestPeopleQueries(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.timezone = "Asia/Kolkata"
        self.team.save()

    def _person(self, uuid: str, *distinct_ids: str, **properties: Any) -> None:
        create_person(team=self.team, uuid=uuid, distinct_ids=list(distinct_ids), properties=properties)

    def _shown_ids(self, page: PeoplePageRows) -> list[str]:
        return [row.distinct_id for row in page.rows]

    def _page(
        self,
        *,
        order: PeopleOrder = PeopleOrder.LAST_SEEN,
        include_anonymous: bool = False,
        new_only: bool = False,
        person_search: str | None = None,
        limit: int = 50,
        offset: int = 0,
        **selection: Any,
    ) -> PeoplePageRows:
        query = PeopleQuery(
            selection=to_selection(self.team, {**WINDOW, **selection}),
            order=order,
            include_anonymous=include_anonymous,
            new_only=new_only,
            person_search=person_search,
        )
        return load_people_page(self.team, self.user, query, PageRequest(limit=limit, offset=offset))

    def _new_people(self, *, include_anonymous: bool = False, **selection: Any) -> tuple[set[str], int, int]:
        page = self._page(new_only=True, include_anonymous=include_anonymous, **selection)
        count = load_new_people_count(
            self.team,
            self.user,
            to_selection(self.team, {**WINDOW, **selection}),
            include_anonymous=include_anonymous,
            person_search=None,
        )
        return {row.person_id for row in page.rows}, page.counts.total, count

    def _seed_three_people(self) -> None:
        self._person(CAROL, "user-carol")
        self._person(DAVE, "user-dave")
        self._person(ERIN, "user-erin")
        seed(
            self.team,
            [
                generation("t-carol", 5, "user-carol", **{"$ai_total_cost_usd": 0.1}),
                generation("t-dave", 3, "user-dave", **{"$ai_total_cost_usd": 0.9}),
                generation("t-erin", 3, "user-erin"),
            ],
        )

    def _seed_anonymous_root_with_identified_generation(self) -> None:
        self._person(CAROL, "user-carol")
        seed(self.team, [anonymous_root("t-1", 1), generation("t-1", 2, "user-carol")])

    def test_a_trace_counts_for_the_identified_user_when_its_root_is_anonymous(self) -> None:
        self._seed_anonymous_root_with_identified_generation()

        page = self._page()

        assert [(shown, row.trace_count) for shown, row in zip(self._shown_ids(page), page.rows)] == [("user-carol", 1)]
        assert page.counts == PeopleCounts(total=1, anonymous=1)

    def test_include_anonymous_lists_the_sdk_fallback_person(self) -> None:
        self._seed_anonymous_root_with_identified_generation()

        page = self._page(include_anonymous=True)

        assert {(shown, row.anonymous) for shown, row in zip(self._shown_ids(page), page.rows)} == {
            ("t-1", True),
            ("user-carol", False),
        }
        assert page.counts == PeopleCounts(total=2, anonymous=1)
        assert (self._new_people()[2], self._new_people(include_anonymous=True)[2]) == (1, 2)

    def test_a_person_with_anonymous_and_identified_traces_is_identified(self) -> None:
        self._person(CAROL, "t-before-identify", "user-carol")
        seed(self.team, [anonymous_root("t-before-identify", 1), generation("t-after-identify", 2, "user-carol")])

        page = self._page()

        assert [(shown, row.anonymous, row.trace_count) for shown, row in zip(self._shown_ids(page), page.rows)] == [
            ("user-carol", False, 2)
        ]
        assert page.counts == PeopleCounts(total=1, anonymous=0)

    def test_a_person_identified_inside_a_trace_counts_it_once(self) -> None:
        self._person(CAROL, "t-1", "user-carol")
        seed(
            self.team,
            [
                anonymous_root("t-1", 1),
                generation("t-1", 2, "user-carol", **{"$ai_total_cost_usd": 0.5}),
            ],
        )

        [row] = self._page().rows

        assert (row.person_id, row.anonymous, row.trace_count, row.cost) == (CAROL, False, 1, 0.5)

    def _seed_a_trace_with_two_people(self) -> None:
        self._person(CAROL, "user-carol")
        self._person(DAVE, "user-dave")
        seed(
            self.team,
            [
                generation("t-shared", 1, "user-carol", **{"$ai_total_cost_usd": 0.5}),
                generation("t-shared", 2, "user-dave", **{"$ai_total_cost_usd": 0.25}),
            ],
        )

    def test_a_trace_with_two_people_counts_for_both_with_only_their_own_events_cost(self) -> None:
        self._seed_a_trace_with_two_people()

        assert {row.person_id: (row.trace_count, row.cost) for row in self._page().rows} == {
            CAROL: (1, 0.5),
            DAVE: (1, 0.25),
        }

    def test_the_person_scope_lists_only_that_person_from_a_shared_trace(self) -> None:
        self._seed_a_trace_with_two_people()

        assert [(row.person_id, row.cost) for row in self._page(person_id=CAROL).rows] == [(CAROL, 0.5)]

    def test_reads_only_the_events_inside_the_range(self) -> None:
        self._person(CAROL, "user-carol")
        seed(
            self.team,
            [
                generation("t-1", -65, "user-carol", **{"$ai_total_cost_usd": 0.5}),
                generation("t-1", 1, "user-carol", **{"$ai_total_cost_usd": 0.25}),
            ],
        )

        [row] = self._page().rows

        assert (row.first_seen_in_range, row.cost) == (at(1), 0.25)

    def test_merged_distinct_ids_give_one_row(self) -> None:
        self._person(CAROL, "user-carol", "carol-phone")
        seed(
            self.team,
            [
                generation("t-both-devices", 1, "user-carol", **{"$ai_total_cost_usd": 0.5}),
                generation("t-both-devices", 2, "carol-phone", **{"$ai_total_cost_usd": 0.5}),
                generation("t-phone", 3, "carol-phone", **{"$ai_total_cost_usd": 0.25}),
            ],
        )

        [row] = self._page().rows

        assert (row.person_id, row.trace_count, row.cost) == (CAROL, 2, 1.25)
        assert (row.first_seen_in_range, row.last_seen) == (at(1), at(3))

    def test_sessions_count_distinct_session_ids(self) -> None:
        self._person(CAROL, "user-carol")
        self._person(DAVE, "user-dave")
        seed(
            self.team,
            [
                generation("t-1", 1, "user-carol", **{"$ai_session_id": "s-1"}),
                generation("t-2", 2, "user-carol", **{"$ai_session_id": "s-1"}),
                generation("t-3", 3, "user-carol", **{"$ai_session_id": "s-2"}),
                generation("t-4", 4, "user-dave"),
            ],
        )

        assert {row.person_id: row.session_count for row in self._page().rows} == {CAROL: 2, DAVE: 0}

    def test_orders_by_last_seen_then_person_id(self) -> None:
        self._seed_three_people()

        assert [row.person_id for row in self._page().rows] == [CAROL, DAVE, ERIN]

    def test_orders_by_cost_highest_first_with_unknown_cost_last(self) -> None:
        self._seed_three_people()

        assert [row.person_id for row in self._page(order=PeopleOrder.COST).rows] == [DAVE, CAROL, ERIN]

    def test_offset_pages_never_repeat_a_row(self) -> None:
        self._seed_three_people()

        first = self._page(order=PeopleOrder.COST, limit=2)
        second = self._page(order=PeopleOrder.COST, limit=2, offset=2)

        assert [row.person_id for row in first.rows] == [DAVE, CAROL]
        assert [row.person_id for row in second.rows] == [ERIN]
        assert first.counts == second.counts == PeopleCounts(total=3, anonymous=0)

    def test_people_with_equal_cost_split_across_pages_by_person_id(self) -> None:
        self._person(DAVE, "user-dave")
        self._person(CAROL, "user-carol")
        seed(
            self.team,
            [
                generation("t-carol", 1, "user-carol", **{"$ai_total_cost_usd": 0.5}),
                generation("t-dave", 2, "user-dave", **{"$ai_total_cost_usd": 0.5}),
            ],
        )

        first = self._page(order=PeopleOrder.COST, limit=1)
        second = self._page(order=PeopleOrder.COST, limit=1, offset=1)

        assert [row.person_id for row in [*first.rows, *second.rows]] == [CAROL, DAVE]

    def test_offset_past_the_end_keeps_the_count(self) -> None:
        self._seed_three_people()

        page = self._page(offset=500)

        assert page.rows == ()
        assert page.counts.total == 3

    def test_new_means_no_activity_in_the_lookback(self) -> None:
        self._person(CAROL, "user-carol")
        self._person(DAVE, "user-dave")
        self._person(ERIN, "user-erin")
        seed(
            self.team,
            [
                generation("t-carol-now", 1, "user-carol"),
                generation("t-carol-before", -10 * DAYS, "user-carol"),
                generation("t-dave-now", 2, "user-dave"),
                generation("t-dave-long-ago", -40 * DAYS, "user-dave"),
                generation("t-dave-before-the-bound", -30 * DAYS - 60 - 5, "user-dave"),
                generation("t-erin-now", 3, "user-erin"),
                generation("t-erin-as-the-range-starts", -55, "user-erin"),
            ],
        )

        assert self._new_people() == ({DAVE, ERIN}, 2, 2)
        assert self._page().counts == PeopleCounts(total=3, anonymous=0)

    @parameterized.expand([("the list", False, 0), ("the new people view", True, 1)])
    def test_only_the_new_view_reads_the_lookback(self, _name: str, new_only: bool, lookbacks: int) -> None:
        self._seed_three_people()

        with self.capture_select_queries() as queries:
            self._page(new_only=new_only)

        assert sum(query.count("globalNotIn(") for query in queries) == lookbacks

    def _time_limits(self, read: Callable[[], object]) -> list[int]:
        with self.capture_select_queries() as queries:
            read()
        return [int(limit) for query in queries for limit in re.findall(r"max_execution_time=(\d+)", query)]

    def test_only_the_list_reads_keep_the_list_time_limit(self) -> None:
        self._seed_three_people()
        general = HogQLGlobalSettings().max_execution_time

        assert self._time_limits(self._page) == [30]
        assert self._time_limits(self._new_people) == [general, general]
        assert self._time_limits(lambda: self._first_seen([CAROL])) == [general]

    def test_new_ignores_property_filters_for_the_lookback(self) -> None:
        self._person(CAROL, "user-carol")
        seed(
            self.team,
            [
                generation("t-now", 1, "user-carol", flavour="vanilla"),
                generation("t-before", -10 * DAYS, "user-carol", flavour="mint"),
            ],
        )
        vanilla = EventPropertyFilter(key="flavour", value="vanilla", operator=PropertyOperator.EXACT)

        assert self._new_people(properties=[vanilla.model_dump()]) == (set(), 0, 0)

    def test_a_filter_matching_one_event_of_a_trace_lists_only_that_events_person(self) -> None:
        self._person(CAROL, "user-carol")
        self._person(DAVE, "user-dave")
        self._person(ERIN, "user-erin")
        seed(
            self.team,
            [
                generation("t-match", 1, "user-carol", flavour="vanilla"),
                generation("t-match", 2, "user-dave"),
                generation("t-other", 3, "user-erin", flavour="mint"),
            ],
        )
        vanilla = EventPropertyFilter(key="flavour", value="vanilla", operator=PropertyOperator.EXACT)

        page = self._page(properties=[vanilla.model_dump()])

        assert [row.person_id for row in page.rows] == [CAROL]

    def test_person_search_matches_display_name_property_and_distinct_id(self) -> None:
        self._person(CAROL, "c-1", email="carol@example.com")
        self._person(DAVE, "user-dave")
        self._person(ERIN, "user-erin", email="erin@example.com")
        seed(
            self.team,
            [
                generation("t-carol", 1, "c-1"),
                generation("t-dave", 2, "user-dave"),
                generation("t-erin", 3, "user-erin"),
            ],
        )

        by_property = self._page(person_search="CAROL@example")
        by_distinct_id = self._page(person_search="r-DAV")

        assert [row.person_id for row in by_property.rows] == [CAROL]
        assert by_property.counts.total == 1
        assert [row.person_id for row in by_distinct_id.rows] == [DAVE]

    def test_person_search_matches_a_merged_distinct_id(self) -> None:
        self._person(CAROL, "carol-old-laptop", "user-carol")
        self._person(DAVE, "user-dave")
        seed(
            self.team,
            [
                generation("t-carol-laptop", 1, "carol-old-laptop"),
                generation("t-carol", 2, "user-carol"),
                generation("t-dave", 3, "user-dave"),
            ],
        )

        page = self._page(person_search="old-LAPTOP")

        assert ([row.person_id for row in page.rows], self._shown_ids(page)) == ([CAROL], ["user-carol"])

    def test_person_search_finds_a_personless_person_by_distinct_id(self) -> None:
        self._person(DAVE, "user-dave")
        seed(
            self.team,
            [
                {**generation("t-erin", 1, "user-erin", **{"$process_person_profile": False}), "person_id": ERIN},
                generation("t-dave", 2, "user-dave"),
            ],
        )

        page = self._page(person_search="R-ERI")

        assert [row.person_id for row in page.rows] == [ERIN]

    def test_test_account_switch_drops_test_people(self) -> None:
        self.team.test_account_filters = [
            {"key": "deployment", "value": ["staging"], "operator": "is_not", "type": "event"}
        ]
        self.team.save()
        self._person(CAROL, "user-carol")
        self._person(DAVE, "user-dave")
        seed(
            self.team,
            [
                generation("t-carol-now", 1, "user-carol"),
                generation("t-carol-staging-before", -10 * DAYS, "user-carol", deployment="staging"),
                generation("t-dave-staging", 2, "user-dave", deployment="staging"),
            ],
        )

        assert [row.person_id for row in self._page(filter_test_accounts=True).rows] == [CAROL]
        assert self._new_people(filter_test_accounts=True) == ({CAROL}, 1, 1)

    def test_another_teams_people_never_list(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other organization"))
        create_person(team=other_team, uuid=CAROL, distinct_ids=["user-carol"])
        seed(other_team, [generation("t-foreign", 1, "user-carol")])

        page = self._page(include_anonymous=True)

        assert page == PeoplePageRows(rows=(), counts=PeopleCounts(total=0, anonymous=0))

    def _first_seen(self, person_ids: list[str], **selection: Any) -> dict[str, PersonFirstSeenRow]:
        return load_people_first_seen(
            self.team, self.user, to_selection(self.team, {**WINDOW, "date_from": 0, **selection}), person_ids
        )

    def test_first_seen_is_the_earliest_event_in_the_lookback(self) -> None:
        self._person(CAROL, "user-carol")
        seed(
            self.team,
            [generation("t-in-range", 5, "user-carol"), generation("t-before", -10 * DAYS, "user-carol")],
        )

        assert self._first_seen([CAROL]) == {CAROL: PersonFirstSeenRow(first_seen=at(-10 * DAYS), is_new=False)}

    def test_first_seen_never_looks_past_the_bound(self) -> None:
        self._person(CAROL, "user-carol")
        seed(
            self.team,
            [generation("t-old", -40 * DAYS, "user-carol"), generation("t-recent", -20 * DAYS, "user-carol")],
        )

        assert self._first_seen([CAROL]) == {CAROL: PersonFirstSeenRow(first_seen=at(-20 * DAYS), is_new=False)}

    def test_first_seen_ignores_the_capture_buffer_around_its_bounds(self) -> None:
        self._person(CAROL, "user-carol")
        self._person(DAVE, "user-dave")
        seed(
            self.team,
            [
                generation("t-before-bound", -30 * DAYS - 5, "user-carol"),
                generation("t-bound", -30 * DAYS + 5, "user-carol"),
                generation("t-after-range", 60 + 5, "user-dave"),
            ],
        )

        assert self._first_seen([CAROL, DAVE]) == {
            CAROL: PersonFirstSeenRow(first_seen=at(-30 * DAYS + 5), is_new=False)
        }

    def test_first_seen_honours_test_accounts_but_not_filters(self) -> None:
        self.team.test_account_filters = [
            {"key": "deployment", "value": ["staging"], "operator": "is_not", "type": "event"}
        ]
        self.team.save()
        self._person(CAROL, "user-carol")
        seed(
            self.team,
            [
                generation("t-staging", -5 * DAYS, "user-carol", deployment="staging"),
                generation("t-prod", -2 * DAYS, "user-carol", model="gpt-test"),
            ],
        )
        other_model = EventPropertyFilter(key="model", value="other", operator=PropertyOperator.EXACT).model_dump()

        assert self._first_seen([CAROL], filter_test_accounts=False, properties=[other_model]) == {
            CAROL: PersonFirstSeenRow(first_seen=at(-5 * DAYS), is_new=False)
        }
        assert self._first_seen([CAROL], filter_test_accounts=True, properties=[other_model]) == {
            CAROL: PersonFirstSeenRow(first_seen=at(-2 * DAYS), is_new=False)
        }

    def test_a_person_with_no_event_in_the_window_is_absent(self) -> None:
        self._person(CAROL, "user-carol")
        self._person(DAVE, "user-dave")
        seed(self.team, [generation("t-carol", 5, "user-carol"), generation("t-dave", -40 * DAYS, "user-dave")])

        assert self._first_seen([CAROL, DAVE, ERIN]) == {CAROL: PersonFirstSeenRow(first_seen=at(5), is_new=True)}
        assert self._first_seen([]) == {}

    def test_first_seen_calls_new_a_person_first_seen_as_the_range_starts(self) -> None:
        self._person(CAROL, "user-carol")
        self._person(DAVE, "user-dave")
        seed(
            self.team,
            [
                generation("t-carol-at-the-start", 0, "user-carol"),
                generation("t-dave-just-before", -1, "user-dave"),
                generation("t-dave-in-range", 5, "user-dave"),
            ],
        )

        assert {person_id: row.is_new for person_id, row in self._first_seen([CAROL, DAVE]).items()} == {
            CAROL: True,
            DAVE: False,
        }
