from uuid import UUID

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ImpossibleASTError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team

_BODY = "SELECT event, count() AS n FROM events WHERE timestamp >= toDateTime('2023-02-01') AND timestamp < toDateTime('2023-02-03') GROUP BY event"
_QUERY = "WITH totals AS ({body}) SELECT sum(l.n) AS total, max(r.n) AS maximum FROM totals l CROSS JOIN totals r"


@override_settings(HOGQL_MATERIALIZED_CTE_SUPPORTED=True)
class TestMaterializedCTEs(SimpleTestCase):
    @parameterized.expand(
        [
            (_BODY, True),
            (_BODY.replace("count()", "any(distinct_id)"), False),
            (_BODY.replace("count()", "groupArray(distinct_id)"), False),
            (_BODY.replace("count()", "sum(rand())"), False),
            (_BODY + " LIMIT 10", False),
            (_BODY.replace("AND timestamp < toDateTime('2023-02-03')", ""), False),
            (
                "SELECT event, 1 AS n FROM events WHERE timestamp >= toDateTime('2023-02-01') AND timestamp < toDateTime('2023-02-03')",
                False,
            ),
        ]
    )
    def test_only_bounded_deterministic_aggregates_are_reused(self, body: str, materialized: bool) -> None:
        sql = self._compile(_QUERY.format(body=body))
        assert ("AS MATERIALIZED" in sql) is materialized

    def _compile(self, query: str, enabled: bool = True, analyzer: bool | None = None) -> str:
        return prepare_and_print_ast(
            parse_select(query),
            dialect="clickhouse",
            context=HogQLContext(
                team=Team(id=1, timezone="UTC"),
                database=Database(timezone="UTC"),
                restricted_properties=set(),
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(materializeRepeatedCTEs=enabled),
            ),
            settings=HogQLGlobalSettings(enable_analyzer=analyzer),
        )[0]

    @parameterized.expand(
        [
            (_QUERY.format(body=_BODY).replace("AS (", "AS NOT MATERIALIZED (", 1), None),
            (_QUERY.format(body=_BODY).replace("AS (", "AS MATERIALIZED (", 1), True),
            (f"WITH totals AS ({_BODY}) SELECT sum(n) FROM totals", False),
            (
                f"WITH totals AS ({_BODY}) SELECT sum(n) FROM totals WHERE event = 'example' UNION ALL SELECT max(n) FROM totals",
                False,
            ),
            (
                f"WITH totals AS ({_BODY}) SELECT sum(n) FROM totals UNION ALL SELECT n FROM (WITH totals AS (SELECT 1 AS n) SELECT n FROM totals)",
                False,
            ),
        ]
    )
    def test_explicit_hints_filters_and_shadowed_scopes(self, query: str, materialized: bool | None) -> None:
        if materialized is None:
            with self.assertRaisesRegex(ImpossibleASTError, "NOT MATERIALIZED"):
                self._compile(query)
        else:
            assert ("AS MATERIALIZED" in self._compile(query)) is materialized

    @parameterized.expand([(False, True, None), (True, False, None), (True, True, False)])
    def test_modifier_capability_and_analyzer_are_required(
        self, enabled: bool, capability: bool, analyzer: bool | None
    ) -> None:
        with override_settings(HOGQL_MATERIALIZED_CTE_SUPPORTED=capability):
            assert "AS MATERIALIZED" not in self._compile(_QUERY.format(body=_BODY), enabled, analyzer)


@override_settings(HOGQL_MATERIALIZED_CTE_SUPPORTED=True)
class TestMaterializedCTEResults(ClickhouseTestMixin, BaseTest):
    allow_dual_schema_snapshots = True

    def test_property_timestamp_does_not_bound_the_event_scan(self) -> None:
        query = _QUERY.format(body=_BODY.replace("timestamp", "properties.timestamp"))
        response = execute_hogql_query(query, self.team, modifiers=HogQLQueryModifiers(materializeRepeatedCTEs=True))
        assert response.clickhouse is not None
        assert "AS MATERIALIZED" not in response.clickhouse

    @parameterized.expand([(False,), (True,)])
    @time_machine.travel("2023-02-03", tick=False)
    def test_reuse_preserves_results_including_empty_data(self, empty: bool) -> None:
        if not empty:
            for event in ["example_a", "example_a", "example_b"]:
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id="example_actor",
                    person_id=UUID(int=1),
                    timestamp="2023-02-01T00:00:00Z",
                )
            flush_persons_and_events()
        query = _QUERY.format(body=_BODY)
        original = execute_hogql_query(query, self.team, modifiers=HogQLQueryModifiers(materializeRepeatedCTEs=False))
        optimized = execute_hogql_query(query, self.team, modifiers=HogQLQueryModifiers(materializeRepeatedCTEs=True))
        assert optimized.results == original.results
        assert optimized.columns == original.columns
        assert optimized.types == original.types
        assert optimized.clickhouse is not None
        assert "AS MATERIALIZED" in optimized.clickhouse
        if not empty:
            self.assertQueryMatchesSnapshot(optimized.clickhouse)
