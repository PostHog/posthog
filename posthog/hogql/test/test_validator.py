from typing import cast

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.validator import (
    HOGQL_PERSONAL_API_KEY_OFFSET_ALLOWED_FLAG,
    OFFSET_NOT_ALLOWED_MESSAGE,
    _OffsetDetectingVisitor,
    validate_personal_api_key_query,
)

from posthog.clickhouse.query_tagging import AccessMethod, tags_context


def _parse(sql: str) -> ast.SelectQuery | ast.SelectSetQuery:
    return cast(ast.SelectQuery | ast.SelectSetQuery, parse_select(sql))


def _flag_resolver(enabled_flags: set[str]):
    def _resolver(flag_key, _distinct_id, **_kwargs):
        return flag_key in enabled_flags

    return _resolver


class TestOffsetDetectingVisitor(BaseTest):
    """AST-level tests, independent of the personal-API-key gate."""

    def _assert_rejects(self, sql: str) -> None:
        with self.assertRaises(QueryError) as ctx:
            _OffsetDetectingVisitor().visit(_parse(sql))
        self.assertEqual(OFFSET_NOT_ALLOWED_MESSAGE, str(ctx.exception))

    def _assert_accepts(self, sql: str) -> None:
        _OffsetDetectingVisitor().visit(_parse(sql))

    def test_rejects_top_level_offset(self):
        self._assert_rejects("SELECT * FROM events WHERE timestamp > now() - INTERVAL 1 DAY LIMIT 100 OFFSET 50")

    def test_rejects_offset_zero(self):
        self._assert_rejects("SELECT event FROM events LIMIT 100 OFFSET 0")

    def test_rejects_offset_in_subquery(self):
        self._assert_rejects("SELECT event FROM (SELECT event FROM events LIMIT 5000 OFFSET 100000) sub")

    def test_rejects_offset_in_cte(self):
        self._assert_rejects("WITH recent AS (SELECT event FROM events LIMIT 5000 OFFSET 10000) SELECT * FROM recent")

    def test_rejects_offset_in_union_branch(self):
        self._assert_rejects("SELECT event FROM events LIMIT 10 UNION ALL SELECT event FROM events LIMIT 10 OFFSET 10")

    def test_rejects_offset_on_select_set_query(self):
        self._assert_rejects(
            "(SELECT event FROM events LIMIT 10) UNION ALL (SELECT event FROM events LIMIT 10) LIMIT 100 OFFSET 5"
        )

    def test_rejects_offset_in_limit_by(self):
        self._assert_rejects("SELECT event, timestamp FROM events LIMIT 5 BY event OFFSET 10")

    def test_rejects_offset_in_joined_subquery(self):
        self._assert_rejects(
            "SELECT e.event FROM events e "
            "JOIN (SELECT distinct_id FROM events LIMIT 100 OFFSET 50) p "
            "ON e.distinct_id = p.distinct_id"
        )

    def test_accepts_query_without_offset(self):
        self._assert_accepts("SELECT event FROM events LIMIT 100")

    def test_accepts_keyset_pagination(self):
        self._assert_accepts(
            "SELECT event, timestamp FROM events WHERE timestamp > '2026-01-01' ORDER BY timestamp LIMIT 5000"
        )

    def test_accepts_aggregation(self):
        self._assert_accepts("SELECT event, count() FROM events GROUP BY event")

    def test_accepts_no_from_events(self):
        self._assert_accepts("SELECT 1")

    def test_accepts_sample_offset(self):
        self._assert_accepts(
            "SELECT event FROM events SAMPLE 1/10 OFFSET 1/10 WHERE timestamp > now() - INTERVAL 1 DAY"
        )


class TestValidatePersonalApiKeyQuery(APIBaseTest):
    """Gate tests — default-block, with an org-level allow-list flag."""

    def _validate(self, sql: str) -> None:
        validate_personal_api_key_query(_parse(sql), team=self.team, user=self.user)

    def test_rejects_offset_by_default_for_personal_api_key(self):
        with (
            tags_context(access_method=AccessMethod.PERSONAL_API_KEY),
            patch("posthoganalytics.feature_enabled", side_effect=_flag_resolver(set())),
        ):
            with self.assertRaises(QueryError) as ctx:
                self._validate("SELECT * FROM events LIMIT 100 OFFSET 50")
            self.assertEqual(OFFSET_NOT_ALLOWED_MESSAGE, str(ctx.exception))

    def test_allows_offset_when_org_on_allow_list(self):
        with (
            tags_context(access_method=AccessMethod.PERSONAL_API_KEY),
            patch(
                "posthoganalytics.feature_enabled",
                side_effect=_flag_resolver({HOGQL_PERSONAL_API_KEY_OFFSET_ALLOWED_FLAG}),
            ),
        ):
            self._validate("SELECT * FROM events LIMIT 100 OFFSET 50")

    def test_allows_offset_when_flag_eval_errors(self):
        with (
            tags_context(access_method=AccessMethod.PERSONAL_API_KEY),
            patch("posthoganalytics.feature_enabled", side_effect=RuntimeError("flag service down")),
        ):
            self._validate("SELECT * FROM events LIMIT 100 OFFSET 50")

    def test_allows_offset_without_personal_api_key(self):
        with patch("posthoganalytics.feature_enabled", side_effect=_flag_resolver(set())):
            self._validate("SELECT * FROM events LIMIT 100 OFFSET 50")

    def test_allows_offset_for_oauth(self):
        with (
            tags_context(access_method=AccessMethod.OAUTH),
            patch("posthoganalytics.feature_enabled", side_effect=_flag_resolver(set())),
        ):
            self._validate("SELECT * FROM events LIMIT 100 OFFSET 50")

    def test_allows_no_offset_with_personal_api_key(self):
        with (
            tags_context(access_method=AccessMethod.PERSONAL_API_KEY),
            patch("posthoganalytics.feature_enabled", side_effect=_flag_resolver(set())),
        ):
            self._validate("SELECT event, count() FROM events GROUP BY event")


class TestValidatorIntegration(APIBaseTest):
    """End-to-end: validation fires in `execute_hogql_query` before ClickHouse."""

    def test_execute_hogql_query_rejects_offset_by_default(self):
        with (
            tags_context(access_method=AccessMethod.PERSONAL_API_KEY),
            patch("posthoganalytics.feature_enabled", side_effect=_flag_resolver(set())),
        ):
            with self.assertRaises(QueryError) as ctx:
                execute_hogql_query(
                    "SELECT event FROM events LIMIT 10 OFFSET 5",
                    team=self.team,
                    user=self.user,
                    pretty=False,
                )
        self.assertEqual(OFFSET_NOT_ALLOWED_MESSAGE, str(ctx.exception))
