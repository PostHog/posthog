from typing import Any, Optional

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.cohort_membership_rewrite import mentions_legacy_table, rewrite_hogql

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
