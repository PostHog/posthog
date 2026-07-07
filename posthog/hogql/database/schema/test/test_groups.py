from datetime import datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team
from posthog.models.group.util import create_group, raw_create_group_ch


class TestGroupsLimitPushdown(ClickhouseTestMixin, APIBaseTest):
    def _team(self) -> Team:
        # Fresh team per test: ClickHouse isn't rolled back, and the inner team_id filter isolates this team's groups.
        return Team.objects.create(organization=self.organization)

    def _run(self, team: Team, query: str) -> tuple[str, list]:
        response = execute_hogql_query(parse_select(query), team)
        assert response.clickhouse is not None
        return response.clickhouse, response.results

    def test_bare_limit_two_phase_returns_correct_deduplicated_rows(self):
        team = self._team()
        # Exactly 10 groups so LIMIT 10 returns all of them (the inner key subquery is unordered).
        for i in range(1, 10):
            create_group(team_id=team.pk, group_type_index=0, group_key=f"g{i:02d}", properties={"name": f"name-{i}"})
        # g00 gets two CH rows (stale + latest) so the outer argMax must still return LATEST under the key limit.
        raw_create_group_ch(team.pk, 0, "g00", {"name": "STALE"}, datetime(2020, 1, 1), timestamp=datetime(2020, 1, 1))
        raw_create_group_ch(team.pk, 0, "g00", {"name": "LATEST"}, datetime(2024, 1, 1), timestamp=datetime(2024, 1, 1))

        sql, results = self._run(team, "SELECT key, properties.name FROM groups LIMIT 10")

        assert len(results) == 10
        # ...the returned keys are distinct (no dedup leak duplicating a group)
        assert len({key for key, _ in results}) == 10
        # ...and g00's value is the latest, not the stale one
        assert dict(results)["g00"] == "LATEST"
        # Assert the two-phase actually fired (results alone can't prove the argMax was limited).
        assert "globalIn(tuple(" in sql
        assert "LIMIT 11" in sql

    def test_aggregate_without_group_by_counts_all_groups(self):
        team = self._team()
        for i in range(12):
            create_group(team_id=team.pk, group_type_index=0, group_key=f"g{i:02d}", properties={})

        # count() collapses to one row, so the limit must not bound the dedup: a buggy pushdown would count 6, not 12.
        sql, results = self._run(team, "SELECT count() FROM groups LIMIT 5")

        assert results[0][0] == 12
        assert "globalIn(tuple(" not in sql

    def test_null_limit_does_not_crash_the_compiler(self):
        team = self._team()
        create_group(team_id=team.pk, group_type_index=0, group_key="g00", properties={})

        # LIMIT NULL is Constant(value=None); the guard must bail rather than crash on `None + 1` (CH rejects it later).
        try:
            self._run(team, "SELECT key FROM groups LIMIT NULL")
        except TypeError:
            raise AssertionError("LIMIT NULL crashed the HogQL compiler with a TypeError")
        except Exception:
            pass

    def test_order_by_limit_returns_global_top_and_is_not_limited(self):
        team = self._team()
        # Global max rank lives on g11; a wrongly-pushed limit could drop it before the ordering runs.
        for i in range(11):
            create_group(team_id=team.pk, group_type_index=0, group_key=f"g{i:02d}", properties={"rank": str(i)})
        create_group(team_id=team.pk, group_type_index=0, group_key="g11", properties={"rank": "999"})

        sql, results = self._run(team, "SELECT key FROM groups ORDER BY toInt(properties.rank) DESC LIMIT 5")

        # real-ClickHouse correctness: the global top-by-rank is returned
        assert len(results) == 5
        assert results[0][0] == "g11"
        # Deterministic check that the key limit was not applied.
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
        # Only g11 matches; a pushed limit would keep the smallest keys and lose it after filtering.
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

        # DISTINCT can collapse limited rows below the requested count, so the limit must not be pushed.
        sql, results = self._run(team, "SELECT DISTINCT key FROM groups LIMIT 5")

        assert len(results) == 5
        assert "LIMIT 6" not in sql

    def test_window_function_is_not_pushed(self):
        team = self._team()
        for i in range(12):
            create_group(team_id=team.pk, group_type_index=0, group_key=f"g{i:02d}", properties={})

        # A window function must see every group; a pushed key limit would compute count() OVER () over the limited
        # set (window funcs aren't caught by the order_by or aggregate guards -- the window's ORDER BY is internal).
        sql, results = self._run(team, "SELECT key, count() OVER () AS total FROM groups LIMIT 5")

        assert results[0][1] == 12
        assert "globalIn(tuple(" not in sql
        assert "LIMIT 6" not in sql

    def test_aliased_groups_select_still_pushes_limit(self):
        team = self._team()
        for i in range(12):
            create_group(team_id=team.pk, group_type_index=0, group_key=f"g{i:02d}", properties={})

        # Aliasing the table must not lose the optimisation; the OOM happens for `groups AS g` too.
        sql, results = self._run(team, "SELECT g.key FROM groups AS g LIMIT 10")

        assert len(results) == 10
        assert "LIMIT 11" in sql

    def test_lazy_join_field_with_limit_returns_correct_groups(self):
        team = self._team()
        for i in range(12):
            create_group(team_id=team.pk, group_type_index=0, group_key=f"g{i:02d}", properties={})

        # revenue_analytics is a row-preserving LEFT JOIN attached after the pushdown, so pushing the limit is safe.
        sql, results = self._run(team, "SELECT key, revenue_analytics.revenue FROM groups LIMIT 10")

        assert len(results) == 10
        assert len({key for key, _ in results}) == 10
        assert "LIMIT 11" in sql
