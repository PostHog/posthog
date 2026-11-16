from django.db.models import Exists, OuterRef, QuerySet, Value
from django.db.models.functions import Concat
from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from posthog.models.file_system.file_system import FileSystem
from posthog.test.sql_pattern_guard import (
    OuterRowPatternError,
    allow_outer_row_pattern,
    fail_on_outer_row_patterns,
    find_column_patterns,
)

_ESCAPED_OUTER_PATH = (
    "REPLACE(REPLACE(REPLACE((COALESCE(\"posthog_filesystem\".\"path\", %s) || COALESCE(%s, %s)), E'\\\\', E'\\\\\\\\'), "
    "E'%%', E'\\\\%%'), E'_', E'\\\\_') || '%%'"
)


class TestFindColumnPatterns(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "outer_ref_prefix_in_exists",
                'SELECT "posthog_filesystem"."id" FROM "posthog_filesystem" WHERE EXISTS(SELECT %s AS "a" '
                f'FROM "posthog_filesystem" "U0" WHERE "U0"."path"::text LIKE {_ESCAPED_OUTER_PATH} LIMIT 1)',
                ["correlated"],
            ),
            (
                "outer_ref_regex_in_subquery",
                'SELECT "posthog_filesystem"."id" FROM "posthog_filesystem" WHERE EXISTS(SELECT 1 '
                'FROM "posthog_filesystem" "U0" WHERE "U0"."path"::text ~ ("posthog_filesystem"."type") LIMIT 1)',
                ["correlated"],
            ),
            (
                "joined_table_prefix",
                "SELECT b.id FROM posthog_filesystem a JOIN posthog_filesystem b ON b.path LIKE a.path || '/%%'",
                ["cross-table"],
            ),
            (
                "same_row_regex",
                'SELECT "posthog_filesystem"."id" FROM "posthog_filesystem" '
                'WHERE "posthog_filesystem"."path"::text ~ ("posthog_filesystem"."type")',
                ["same-row"],
            ),
            (
                "same_row_inside_subquery",
                'SELECT "posthog_filesystem"."id" FROM "posthog_filesystem" WHERE EXISTS(SELECT 1 '
                'FROM "posthog_filesystem" "U0" WHERE "U0"."path"::text LIKE "U0"."type" || \'%%\' LIMIT 1)',
                ["same-row"],
            ),
            (
                "parameter_prefix",
                'SELECT "posthog_filesystem"."id" FROM "posthog_filesystem" WHERE "posthog_filesystem"."path"::text LIKE %s',
                [],
            ),
            (
                "literal_prefix_in_subquery",
                'SELECT 1 FROM "posthog_filesystem" WHERE EXISTS(SELECT 1 FROM "posthog_filesystem" "U0" '
                'WHERE UPPER("U0"."path"::text) LIKE UPPER(\'Unfiled/%%\'))',
                [],
            ),
            (
                "no_operator",
                'SELECT "posthog_filesystem"."id" FROM "posthog_filesystem" WHERE "posthog_filesystem"."path" = %s',
                [],
            ),
        ]
    )
    def test_classifies_pattern_operands(self, _name: str, sql: str, expected_kinds: list[str]) -> None:
        assert [pattern.kind for pattern in find_column_patterns(sql)] == expected_kinds


def _files_with_a_child() -> QuerySet:
    children = FileSystem.objects.filter(path__startswith=Concat(OuterRef("path"), Value("/")))
    return FileSystem.objects.filter(Exists(children))


class TestFailOnOuterRowPatterns(TestCase):
    def test_correlated_pattern_fails_with_its_source_and_fix(self) -> None:
        with self.assertRaises(OuterRowPatternError) as raised:
            with fail_on_outer_row_patterns():
                list(_files_with_a_child())

        message = str(raised.exception)
        assert "kind:    correlated" in message
        assert "posthog/test/test_sql_pattern_guard.py" in message
        assert "allow_outer_row_pattern" in message

    def test_allowed_pattern_passes(self) -> None:
        with fail_on_outer_row_patterns(), allow_outer_row_pattern(reason="the table holds one row per project"):
            assert list(_files_with_a_child()) == []
