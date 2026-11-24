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
            ("element_access", "elements_chain_elements[1]", "events", "button"),
            (
                "length_guard",
                "if(length(elements_chain_elements) > 0, elements_chain_elements[1], '')",
                "events",
                "button",
            ),
            ("array_element", "arrayElement(elements_chain_elements, 1)", "events", "button"),
            ("array_first_without_match", "arrayFirst(x -> x = 'form', elements_chain_elements)", "events", ""),
            (
                "array_last_with_a_second_array",
                "arrayLast((x, y) -> y = 'none', elements_chain_elements, elements_chain_texts)",
                "events",
                "",
            ),
            ("subquery", "e[1]", "(select event, elements_chain_elements as e from events)", "button"),
        ]
    )
    def test_reading_one_tag_from_an_event_without_elements(
        self, _name: str, expression: str, source: str, button_value: str
    ) -> None:
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="d1",
            timestamp="2026-01-01T00:00:00Z",
            elements_chain='button.btn:text="Submit"',
        )
        _create_event(event="$pageview", team=self.team, distinct_id="d1", timestamp="2026-01-01T00:01:00Z")

        response = execute_hogql_query(
            f"select event, {expression} as tag from {source}",
            team=self.team,
        )

        self.assertCountEqual(response.results, [("$autocapture", button_value), ("$pageview", "")])

    @parameterized.expand([("subquery", False), ("cte", True)])
    def test_union_matches_the_element_array_by_position(self, _name: str, use_cte: bool) -> None:
        _create_event(event="$pageview", team=self.team, distinct_id="visitor")
        source = """
            SELECT [7] AS numbers, [] AS tags
            UNION ALL
            SELECT [8] AS more_numbers, elements_chain_elements AS numbers FROM events
        """
        select = "SELECT numbers[1], tags[1]"
        response = execute_hogql_query(
            f"WITH u AS ({source}) {select} FROM u" if use_cte else f"{select} FROM ({source})",
            team=self.team,
        )
        self.assertCountEqual(response.results, [(7, ""), (8, "")])
