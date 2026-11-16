from typing import Any, Optional

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.cohortmembership.query_rewrite import mentions_legacy_table, rewrite_hogql, rewrite_query_nodes

MEMBERSHIP_FILTER = (
    "SELECT count() FROM events e WHERE e.person_id IN (SELECT person_id FROM cohort_membership WHERE cohort_id = 7)"
)


class TestRewriteHogQL(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "subquery_filter",
                MEMBERSHIP_FILTER,
                True,
                MEMBERSHIP_FILTER.replace("cohort_membership", "cohort_people"),
            ),
            (
                "aliased_join",
                "SELECT count() FROM events e JOIN cohort_membership AS cm ON cm.person_id = e.person_id",
                True,
                "SELECT count() FROM events e JOIN cohort_people AS cm ON cm.person_id = e.person_id",
            ),
            (
                "qualified_by_table_name",
                "SELECT cohort_membership.person_id FROM cohort_membership WHERE cohort_membership.cohort_id = 7",
                True,
                "SELECT cohort_membership.person_id FROM cohort_people AS cohort_membership WHERE cohort_membership.cohort_id = 7",
            ),
            (
                "posthog_namespace",
                "SELECT person_id FROM posthog.cohort_membership WHERE cohort_id = 7",
                True,
                "SELECT person_id FROM cohort_people WHERE cohort_id = 7",
            ),
            (
                "two_references",
                "SELECT count() FROM events WHERE person_id NOT IN (SELECT person_id FROM cohort_membership WHERE cohort_id = 7)"
                " AND person_id NOT IN (SELECT person_id FROM cohort_membership WHERE cohort_id = 8)",
                True,
                "SELECT count() FROM events WHERE person_id NOT IN (SELECT person_id FROM cohort_people WHERE cohort_id = 7)"
                " AND person_id NOT IN (SELECT person_id FROM cohort_people WHERE cohort_id = 8)",
            ),
            (
                "outer_select_star_is_another_scope",
                "SELECT * FROM events WHERE person_id IN (SELECT person_id FROM cohort_membership WHERE cohort_id = 7)",
                True,
                "SELECT * FROM events WHERE person_id IN (SELECT person_id FROM cohort_people WHERE cohort_id = 7)",
            ),
            (
                "count_star",
                "SELECT count(*) FROM cohort_membership WHERE cohort_id = 7",
                True,
                "SELECT count(*) FROM cohort_people WHERE cohort_id = 7",
            ),
            ("reads_status", "SELECT person_id FROM cohort_membership WHERE status = 'entered'", True, None),
            ("reads_aliased_last_updated", "SELECT max(cm.last_updated) FROM cohort_membership cm", True, None),
            (
                "reads_namespaced_status",
                "SELECT person_id FROM posthog.cohort_membership WHERE posthog.cohort_membership.status = 'entered'",
                True,
                None,
            ),
            ("select_star", "SELECT * FROM cohort_membership", True, None),
            (
                "reads_status_qualified_by_table_name",
                "SELECT cohort_membership.status FROM cohort_membership",
                True,
                None,
            ),
            ("aliased_star", "SELECT cm.* FROM cohort_membership cm", True, None),
            ("unparseable", "SELECT FROM cohort_membership WHERE", True, None),
            ("leading_byte_order_mark", "﻿SELECT person_id FROM cohort_membership WHERE cohort_id = 7", True, None),
            (
                "cte_with_the_same_name",
                "WITH cohort_membership AS (SELECT person_id FROM cohort_people) SELECT person_id FROM cohort_membership",
                True,
                None,
            ),
            (
                "cte_in_the_first_union_branch",
                "WITH cohort_membership AS (SELECT 1 AS person_id) SELECT person_id FROM cohort_membership"
                " UNION ALL SELECT person_id FROM cohort_membership",
                True,
                None,
            ),
            (
                "cte_named_like_the_replacement",
                "WITH cohort_people AS (SELECT 1 AS person_id) SELECT person_id FROM cohort_membership",
                True,
                None,
            ),
            (
                "joined_with_the_replacement",
                "SELECT count() FROM cohort_membership JOIN cohort_people USING (person_id)",
                True,
                None,
            ),
            (
                "count_star_filter_reads_status",
                "SELECT count(*) FILTER (WHERE status = 'entered') FROM cohort_membership",
                True,
                None,
            ),
            ("columns_pattern", "SELECT COLUMNS('status') FROM cohort_membership", True, None),
            ("positional_column_aliases", "SELECT c FROM cohort_membership AS cm(c, p)", True, None),
            (
                "column_or_text_only",
                "SELECT 'cohort_membership' AS name, cohort_membership_changed FROM events",
                False,
                None,
            ),
        ]
    )
    def test_rewrite_hogql(self, _name: str, sql: str, reads_table: bool, expected_after: Optional[str]) -> None:
        rewrite = rewrite_hogql(sql)
        assert (rewrite is not None) is reads_table
        assert (rewrite.after if rewrite else None) == expected_after

    @parameterized.expand(
        [
            ("table_after_a_newline", {"code": "SELECT person_id FROM\ncohort_membership"}, True),
            ("namespaced_table", ["SELECT 1 FROM posthog.cohort_membership"], True),
            (
                "alias_the_rewrite_adds",
                {"query": "SELECT cohort_membership.person_id FROM cohort_people AS cohort_membership"},
                False,
            ),
            ("longer_name", {"event": "cohort_membership_changed"}, False),
        ]
    )
    def test_mentions_legacy_table(self, _name: str, value: Any, expected: bool) -> None:
        assert mentions_legacy_table(value) is expected

    @parameterized.expand(
        [
            ("posthog", {}, True),
            ("direct_connection", {"connectionId": "source"}, False),
            ("hosted_trino", {"executionTarget": "managed_trino"}, False),
        ]
    )
    def test_rewrite_query_nodes_only_rewrites_queries_posthog_runs(
        self, _name: str, engine: dict[str, Any], rewritten: bool
    ) -> None:
        query = {"kind": "HogQLQuery", "query": MEMBERSHIP_FILTER, **engine}
        result, _ = rewrite_query_nodes(query)
        assert ("cohort_people" in result["query"]) is rewritten
