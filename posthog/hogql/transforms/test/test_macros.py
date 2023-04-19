from posthog.hogql.parser import parse_select
from posthog.hogql.transforms.macros import expand_macros
from posthog.test.base import BaseTest


class TestMacroExpander(BaseTest):
    def test_macros_basic_column(self):
        self.assertEqual(
            expand_macros(parse_select("with 1 as macro select macro from events")),
            parse_select("select 1 from events"),
        )

    def test_macros_recursive_column(self):
        self.assertEqual(
            expand_macros(parse_select("with 1 as macro, macro as soap select soap from events")),
            parse_select("select 1 from events"),
        )

    def test_macros_subqueries(self):
        self.assertEqual(
            expand_macros(parse_select("with my_table as (select * from events) select * from my_table")),
            parse_select("select * from (select * from events) my_table"),
        )

        self.assertEqual(
            expand_macros(
                parse_select("with my_table as (select * from events) select my_table.timestamp from my_table")
            ),
            parse_select("select my_table.timestamp from (select * from events) my_table"),
        )

        self.assertEqual(
            expand_macros(parse_select("with my_table as (select * from events) select timestamp from my_table")),
            parse_select("select timestamp from (select * from events) my_table"),
        )

    def test_macros_subquery_deep(self):
        self.assertEqual(
            expand_macros(
                parse_select(
                    "with my_table as (select * from events), "
                    "other_table as (select * from (select * from (select * from my_table))) "
                    "select * from other_table"
                )
            ),
            parse_select(
                "select * from (select * from (select * from (select * from (select * from events) as my_table))) as other_table"
            ),
        )

    def test_macros_subquery_recursion(self):
        query = "with users as (select event, timestamp as tt from events ), final as ( select tt from users ) select * from final"
        self.assertEqual(
            expand_macros(parse_select(query)),
            parse_select(
                "select * from (select tt from (select event, timestamp as tt from events) AS users) AS final"
            ),
        )
