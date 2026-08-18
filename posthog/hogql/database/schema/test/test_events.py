from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event

from parameterized import parameterized

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.uuidt import uuid7


class TestEvents(ClickhouseTestMixin, APIBaseTest):
    def test_select_star_from_events(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": session_id},
        )

        response = execute_hogql_query(
            parse_select(
                "select * from events",
            ),
            team=self.team,
        )

        self.assertEqual(
            len(response.results or []),
            1,
        )

    @parameterized.expand(
        [
            # A length guard does not save the raw enum column: ClickHouse if() has no
            # short-circuit, so arrayElement still runs over every row.
            (
                "length_guard",
                "if(length(elements_chain_elements) > 0, elements_chain_elements[1], '(unknown)')",
                "(unknown)",
            ),
            # Wrapping in toString does not save it either: the invalid enum value is read before the cast.
            ("to_string", "toString(elements_chain_elements[1])", ""),
        ]
    )
    def test_index_elements_chain_elements_without_enum_error(self, _name: str, expression: str, empty_value: str):
        # The stored column is Array(Enum8(...)) with no member for 0, so indexing an empty row
        # once raised "Unexpected value 0 in enum". The field now resolves to Array(String).
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="d1",
            timestamp="2024-01-01T00:00:00Z",
            elements_chain='button.btn:text="Submit"',
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            timestamp="2024-01-01T00:01:00Z",
        )

        response = execute_hogql_query(
            parse_select(f"select {expression} as tag from events order by timestamp"),
            team=self.team,
        )

        self.assertEqual(response.results, [("button",), (empty_value,)])
