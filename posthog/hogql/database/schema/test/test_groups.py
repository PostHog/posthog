from datetime import datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team
from posthog.models.group.util import create_group, raw_create_group_ch


class TestGroupsLimitPushdown(ClickhouseTestMixin, APIBaseTest):
    def _team(self) -> Team:
        # Fresh team per test: ClickHouse isn't rolled back between tests, but the mandatory inner
        # team_id filter isolates this team's groups (and, being inner, doesn't suppress the pushdown
        # the way an outer WHERE would).
        return Team.objects.create(organization=self.organization)

    def _run(self, team: Team, query: str) -> tuple[str, list]:
        response = execute_hogql_query(parse_select(query), team)
        assert response.clickhouse is not None
        return response.clickhouse, response.results

    def test_bare_limit_pushdown_returns_correct_deduplicated_rows(self):
        team = self._team()
        for i in range(1, 12):
            create_group(team_id=team.pk, group_type_index=0, group_key=f"g{i:02d}", properties={"name": f"name-{i}"})
        # g00 (smallest key, always inside the limit window) has two ClickHouse rows: an older stale version
        # and a newer one. The query-time dedup must argMax to LATEST; a pushdown that truncated the per-group
        # aggregation would return STALE. Written straight to ClickHouse since one group key = one Postgres row.
        raw_create_group_ch(team.pk, 0, "g00", {"name": "STALE"}, datetime(2020, 1, 1), timestamp=datetime(2020, 1, 1))
        raw_create_group_ch(team.pk, 0, "g00", {"name": "LATEST"}, datetime(2024, 1, 1), timestamp=datetime(2024, 1, 1))

        sql, results = self._run(team, "SELECT key, properties.name FROM groups LIMIT 10")

        # the pushdown must not under-return: 12 groups exist, 10 requested
        assert len(results) == 10
        # ...the returned keys are distinct (no dedup leak duplicating a group)
        assert len({key for key, _ in results}) == 10
        # ...and g00's value is the latest, not the stale one
        assert dict(results)["g00"] == "LATEST"
        # the optimisation is actually applied (results alone can't prove it wasn't silently dropped)
        assert "optimize_aggregation_in_order=1" in sql
        assert "LIMIT 11" in sql

    def test_order_by_limit_returns_global_top_and_is_not_pushed(self):
        team = self._team()
        # rank rises with key for g00..g10, but the global max rank lives on g11, the largest key. If the limit
        # were pushed into the dedup, ClickHouse would (at scale) keep the smallest keys and drop g11.
        for i in range(11):
            create_group(team_id=team.pk, group_type_index=0, group_key=f"g{i:02d}", properties={"rank": str(i)})
        create_group(team_id=team.pk, group_type_index=0, group_key="g11", properties={"rank": "999"})

        sql, results = self._run(team, "SELECT key FROM groups ORDER BY toInt(properties.rank) DESC LIMIT 5")

        # real-ClickHouse correctness: the global top-by-rank is returned
        assert len(results) == 5
        assert results[0][0] == "g11"
        # deterministic guard check: the limit was not pushed into the dedup (the wrong result it would cause
        # only surfaces once in-order aggregation engages, which it doesn't at unit-test scale)
        assert "LIMIT 6" not in sql

    @parameterized.expand(
        [
            ("where", "SELECT key FROM groups WHERE properties.tag = 'needle' LIMIT 5"),
            # HAVING is a post-dedup filter just like WHERE; pushing the limit before it would under-return.
            ("having", "SELECT key FROM groups HAVING properties.tag = 'needle' LIMIT 5"),
        ]
    )
    def test_post_dedup_filter_is_not_pushed(self, _name, query):
        team = self._team()
        # Only g11 (largest key) matches the filter. A pushed limit would keep the smallest keys, filter after,
        # and lose the matching row.
        for i in range(11):
            create_group(team_id=team.pk, group_type_index=0, group_key=f"g{i:02d}", properties={"tag": "haystack"})
        create_group(team_id=team.pk, group_type_index=0, group_key="g11", properties={"tag": "needle"})

        sql, results = self._run(team, query)

        assert len(results) == 1
        assert results[0][0] == "g11"
        assert "LIMIT 6" not in sql

    def test_array_join_is_not_pushed(self):
        team = self._team()
        for i in range(12):
            create_group(team_id=team.pk, group_type_index=0, group_key=f"g{i:02d}", properties={})

        # ARRAY JOIN can drop source rows (empty array) after the dedup, so the limit must not be pushed into it.
        sql, _ = self._run(team, "SELECT key FROM groups ARRAY JOIN [1, 2] AS x LIMIT 5")

        assert "LIMIT 6" not in sql

    def test_distinct_limit_is_not_pushed(self):
        team = self._team()
        for i in range(8):
            create_group(team_id=team.pk, group_type_index=0, group_key=f"g{i:02d}", properties={})

        # DISTINCT can collapse the limited rows below the requested count (e.g. a key shared across group types),
        # so the limit must not be pushed into the dedup.
        sql, results = self._run(team, "SELECT DISTINCT key FROM groups LIMIT 5")

        assert len(results) == 5
        assert "LIMIT 6" not in sql

    def test_aliased_groups_select_still_pushes_limit(self):
        team = self._team()
        for i in range(12):
            create_group(team_id=team.pk, group_type_index=0, group_key=f"g{i:02d}", properties={})

        # Aliasing the table must not lose the optimisation -- the OOM this guards against happens for `groups AS g` too.
        sql, results = self._run(team, "SELECT g.key FROM groups AS g LIMIT 10")

        assert len(results) == 10
        assert "LIMIT 11" in sql

    def test_lazy_join_field_with_limit_returns_correct_groups(self):
        team = self._team()
        for i in range(12):
            create_group(team_id=team.pk, group_type_index=0, group_key=f"g{i:02d}", properties={})

        # The revenue_analytics lazy join is attached after the pushdown runs, so the limit is pushed through it.
        # That stays correct because it's a row-preserving LEFT JOIN: all 10 requested groups still come back.
        sql, results = self._run(team, "SELECT key, revenue_analytics.revenue FROM groups LIMIT 10")

        assert len(results) == 10
        assert len({key for key, _ in results}) == 10
        assert "LIMIT 11" in sql
