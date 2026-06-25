from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.group.util import create_group


class TestGroupsLimitPushdown(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        for i in range(12):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i:02d}",
                properties={"name": f"Org {i}"},
            )

    def _run(self, query: str) -> tuple[str, list]:
        response = execute_hogql_query(parse_select(query), self.team)
        assert response.clickhouse is not None
        return response.clickhouse, response.results

    def test_dedup_aggregates_in_order_and_pushes_limit(self):
        sql, results = self._run("SELECT key, properties FROM groups LIMIT 10")
        # in-order aggregation finalizes each group as the scan passes it, instead of buffering an argMax state
        # (carrying group_properties) for every group -- this is what stops the OOM
        assert "optimize_aggregation_in_order=1" in sql
        # the outer LIMIT is copied into the dedup (10 + offset 0 + 1) so the scan can stop early
        assert "LIMIT 11" in sql
        assert len(results) == 10

    @parameterized.expand(
        [
            # ORDER BY: pushing a bare LIMIT into the dedup would keep the wrong 10 groups (storage order, not key order)
            ("order_by_desc", "SELECT key FROM groups ORDER BY key DESC LIMIT 10", 10, "org:11"),
            # WHERE: pushing the LIMIT before the filter could drop the matching group entirely
            ("where_eq", "SELECT key FROM groups WHERE key = 'org:00' LIMIT 10", 1, "org:00"),
        ]
    )
    def test_does_not_push_limit_when_unsafe(self, _name, query, expected_count, expected_first_key):
        sql, results = self._run(query)
        # memory is still bounded via in-order aggregation...
        assert "optimize_aggregation_in_order=1" in sql
        # ...but the limit must not reach the dedup, or it would drop rows the outer clause still needs
        assert "LIMIT 11" not in sql
        assert len(results) == expected_count
        assert results[0][0] == expected_first_key
