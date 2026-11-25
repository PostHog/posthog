from dataclasses import replace
from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import EventPropertyFilter, PropertyOperator

from products.ai_observability.backend.logic.people.people import (
    PeopleCounts,
    PeopleOrder,
    PeopleQuery,
    listed_person_label,
    needs_identification,
)
from products.ai_observability.backend.logic.traces.trace_selection import TraceGroupScope, TraceSelection, TraceWindow

START = datetime(2026, 10, 5, tzinfo=UTC)
SELECTION = TraceSelection(window=TraceWindow(start=START, end=START + timedelta(days=7)))
ONLY_ANONYMOUS = PeopleCounts(total=0, anonymous=3)


def _query(
    *,
    include_anonymous: bool = False,
    new_only: bool = False,
    person_search: str | None = None,
    selection: TraceSelection = SELECTION,
) -> PeopleQuery:
    return PeopleQuery(
        selection=selection,
        order=PeopleOrder.LAST_SEEN,
        include_anonymous=include_anonymous,
        new_only=new_only,
        person_search=person_search,
    )


class TestPeople(SimpleTestCase):
    @parameterized.expand(
        [
            ("only_anonymous_switch_off", ONLY_ANONYMOUS, _query(), True),
            (
                "only_anonymous_switch_on",
                PeopleCounts(total=3, anonymous=3),
                _query(include_anonymous=True),
                False,
            ),
            ("no_traces", PeopleCounts(total=0, anonymous=0), _query(), False),
            ("identified_people", PeopleCounts(total=2, anonymous=3), _query(), False),
            ("a_search_that_finds_only_anonymous_people", ONLY_ANONYMOUS, _query(person_search="carol"), False),
            ("a_blank_search", ONLY_ANONYMOUS, _query(person_search="  "), True),
            ("the_new_chip_that_finds_only_anonymous_people", ONLY_ANONYMOUS, _query(new_only=True), False),
            (
                "a_person_scope",
                ONLY_ANONYMOUS,
                _query(selection=replace(SELECTION, person_id="00000000-0000-4000-8000-00000000000c")),
                False,
            ),
            (
                "a_group_scope",
                ONLY_ANONYMOUS,
                _query(selection=replace(SELECTION, group=TraceGroupScope(key="acme", type_index=0))),
                False,
            ),
            (
                "a_property_filter",
                ONLY_ANONYMOUS,
                _query(
                    selection=replace(
                        SELECTION,
                        properties=(
                            EventPropertyFilter(key="flavour", value="vanilla", operator=PropertyOperator.EXACT),
                        ),
                    )
                ),
                False,
            ),
            (
                "the_test_account_switch",
                ONLY_ANONYMOUS,
                _query(selection=replace(SELECTION, filter_test_accounts=True)),
                True,
            ),
        ]
    )
    def test_needs_identification(self, _name: str, counts: PeopleCounts, query: PeopleQuery, expected: bool) -> None:
        assert needs_identification(counts, query) is expected

    @parameterized.expand(
        [
            ("anonymous, by the start of the distinct id", True, "f81d4fae-7dec-11d0", "Bo", "Anonymous f81d4fae"),
            ("identified, by the display name", False, "user-bo", "bo@example.com", "bo@example.com"),
            ("identified with no display name, by the distinct id", False, "user-bo", None, "user-bo"),
        ]
    )
    def test_labels_a_listed_person(
        self, _name: str, anonymous: bool, distinct_id: str, display_name: str | None, label: str
    ) -> None:
        assert listed_person_label(anonymous=anonymous, distinct_id=distinct_id, display_name=display_name) == label
