from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.query import HogQLQueryExecutor


class TestDirectPostgresQuery(APIBaseTest):
    @parameterized.expand(
        [
            (
                "unaliased_table",
                ast.TableType(
                    table=DirectPostgresTable(
                        name="postgres.ph3.ph3_postgres_posthog_activitylog",
                        fields={},
                        postgres_schema="ph3",
                        postgres_table_name="ph3_postgres_posthog_activitylog",
                        external_data_source_id="source-id",
                    )
                ),
            ),
            (
                "aliased_table",
                ast.TableAliasType(
                    alias="activitylog",
                    table_type=ast.TableType(
                        table=DirectPostgresTable(
                            name="postgres.ph3.ph3_postgres_posthog_activitylog",
                            fields={},
                            postgres_schema="ph3",
                            postgres_table_name="ph3_postgres_posthog_activitylog",
                            external_data_source_id="source-id",
                        )
                    ),
                ),
            ),
        ]
    )
    def test_extract_direct_postgres_source_ids(self, _name: str, table_type: ast.TableType | ast.TableAliasType):
        executor = HogQLQueryExecutor(query="SELECT 1", team=self.team)
        query_type = ast.SelectQueryType(tables={"postgres.ph3.ph3_postgres_posthog_activitylog": table_type})

        source_ids = executor._extract_direct_postgres_sources_from_type(query_type)

        self.assertEqual(source_ids, {"source-id"})
