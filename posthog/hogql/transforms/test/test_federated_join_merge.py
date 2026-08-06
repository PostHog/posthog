from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.transforms.federated_join_merge import MERGED_ALIAS

ACCOUNTS_LAZY_JOINS_QUERY = """
    select id, accounts.tags.names as tag_names, accounts.notebooks.count as notebook_count
    from system.accounts as accounts
"""

EXPLICIT_JOINS_QUERY_TEMPLATE = """
    select accounts.id, tag_agg.tag_count, note_agg.note_col
    from system.accounts as accounts
    left join (
        select account_id as account_id, count() as tag_count
        from system._account_tagged_items
        group by account_id
    ) as tag_agg on tag_agg.account_id = accounts.id
    left join (
        select account_id as account_id, {note_expr} as note_col
        from system._account_resource_notebooks
        group by account_id
    ) as note_agg on note_agg.account_id = accounts.id
"""


class TestFederatedJoinMerge(BaseTest):
    def _print_select(self, select: str, merge_enabled: bool = True) -> str:
        printed, _ = prepare_and_print_ast(
            parse_select(select),
            HogQLContext(
                team=self.team,
                user=self.user,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(mergeFederatedAggregateJoins=merge_enabled),
            ),
            "clickhouse",
        )
        return printed

    def test_sibling_aggregating_lazy_joins_merge(self):
        printed = self._print_select(ACCOUNTS_LAZY_JOINS_QUERY)
        self.assertIn(MERGED_ALIAS, printed)
        self.assertIn("UNION ALL", printed)

    def test_explicit_aggregating_joins_merge(self):
        printed = self._print_select(EXPLICIT_JOINS_QUERY_TEMPLATE.format(note_expr="count()"))
        self.assertIn(MERGED_ALIAS, printed)
        self.assertIn("UNION ALL", printed)

    @parameterized.expand(
        [
            (
                "single_aggregating_join",
                "select id, accounts.notebooks.count as notebook_count from system.accounts as accounts",
                True,
            ),
            ("modifier_off", ACCOUNTS_LAZY_JOINS_QUERY, False),
            # any(notebook_id) is a non-nullable non-count scalar: its join-miss default
            # can't be told apart from a real value after the union, so it disqualifies
            # its join and drops the candidate count below two.
            (
                "non_nullable_scalar_aggregate",
                EXPLICIT_JOINS_QUERY_TEMPLATE.format(note_expr="any(notebook_id)"),
                True,
            ),
        ]
    )
    def test_no_merge(self, _name: str, query: str, merge_enabled: bool):
        printed = self._print_select(query, merge_enabled=merge_enabled)
        self.assertNotIn(MERGED_ALIAS, printed)
