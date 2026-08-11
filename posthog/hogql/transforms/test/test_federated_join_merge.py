from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.transforms.federated_join_merge import MERGED_ALIAS

from products.data_tools.backend.models.join import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

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

    def test_reserved_alias_already_taken_skips_merge(self):
        # A user-authored join under the reserved alias must disable the merge for the
        # select instead of colliding with the transform's generated join.
        query = f"""
            select accounts.id, tag_agg.tag_count, note_agg.note_col, {MERGED_ALIAS}.c
            from system.accounts as accounts
            left join (
                select account_id as account_id, count() as tag_count
                from system._account_tagged_items group by account_id
            ) as tag_agg on tag_agg.account_id = accounts.id
            left join (
                select account_id as account_id, count() as note_col
                from system._account_resource_notebooks group by account_id
            ) as note_agg on note_agg.account_id = accounts.id
            left join (
                select account_id as account_id, count() as c
                from system._account_tagged_items group by account_id
            ) as {MERGED_ALIAS} on {MERGED_ALIAS}.account_id = accounts.id
        """
        printed = self._print_select(query)
        self.assertNotIn("UNION ALL", printed)

    def test_warehouse_join_columns_compile_alongside_aggregating_joins(self):
        # Merging warehouse (s3) joins breaks compilation ("Can't access field on
        # LazyJoinType"), so the transform must exclude them. Printing is enough to
        # catch the regression, and no s3 read happens here.
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        DataWarehouseTable.objects.create(
            name="account_list",
            format=DataWarehouseTable.TableFormat.CSVWithNames,
            team=self.team,
            credential=credential,
            url_pattern="http://localhost:19000/bucket/account_list/*.csv",
            columns={
                "external_id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "valid": True},
                "total_mrr": {"hogql": "FloatDatabaseField", "clickhouse": "Nullable(Float64)", "valid": True},
            },
        )
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="system.accounts",
            source_table_key="external_id",
            joining_table_name="account_list",
            joining_table_key="external_id",
            field_name="account_list",
        )

        printed = self._print_select(
            """
            select id, accounts.tags.names as tag_names, accounts.notebooks.count as notebook_count,
                   accounts.account_list.total_mrr as mrr
            from system.accounts as accounts
            """
        )
        self.assertIn("account_list", printed)
