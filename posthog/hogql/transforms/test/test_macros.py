from posthog.hogql.parser import parse_select
from posthog.hogql.transforms.macros import expand_macros
from posthog.test.base import BaseTest


class TestMacroExpander(BaseTest):
    def test_macro_expander(self):
        self.assertEqual(
            expand_macros(parse_select("with 1 as macro select macro from events")),
            parse_select("select 1 from events"),
        )

        self.assertEqual(
            expand_macros(parse_select("with my_table as (select * from events) select * from my_table")),
            parse_select("select * from (select * from events)"),
        )
