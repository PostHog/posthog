"""Execution-level characterization tests for HogQL property handling (printer rearchitecture, PR0c).

These tests pin behavior the golden SQL text cannot — they run real ClickHouse and assert on *results* and
*skip-index usage*, which is the correctness gate for the rearchitecture (doc §9.4, §12.6). SQL text is
result-equivalent, not byte-stable, so it is deliberately not asserted here.

Two suites:

- ``TestPersonPropertyIsNotSet`` locks the §8.2 semantics: a non-nullable materialized column stores ``''`` for both
  empty-string and missing, so it cannot answer "is it set". The test runs is_not_set across PersonsOnEventsMode
  (joined vs on-events) × materialized vs not and asserts the value/flag results, plus that the materialized path emits
  no JSON/Has operation on the blob (the performance regression the column exists to prevent).
- ``TestPhysicalScenarios`` drives the ``PHYSICAL_SCENARIOS`` corpus: it materializes the named column(s), inserts
  match/no-match events, runs the HogQL, and asserts results + the expected skip index. It includes the ``mat_is_not_set``
  footgun (§8.2) in execution form. NOTE: the corpus ``description`` for that scenario states the rearchitecture
  *target* (decline onto the blob); this test instead locks current **master** behavior, which is the footgun itself —
  ``properties.test_prop IS NULL`` over a non-nullable materialized column reads the scrubbed mat column
  (``isNull(nullIf(nullIf(mat_test_prop, ''), 'null'))``), so empty-string and the literal ``"null"`` string both
  collapse to "not set". The test makes that divergence from the truthful JSON-blob answer explicit and
  machine-checked, so when the rearchitecture flips the behavior the expectation here flips with it.

All of this characterizes correct MASTER behavior and must pass on master — it adds no production behavior.
"""

from typing import cast

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    cleanup_materialized_columns,
    flush_persons_and_events,
    get_index_from_explain,
)

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode, PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.printer.test.property_corpus import PHYSICAL_SCENARIOS, PhysicalScenario
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from ee.clickhouse.materialized_columns.columns import get_minmax_index_name, materialize


class TestPersonPropertyIsNotSet(ClickhouseTestMixin, APIBaseTest):
    """is_not_set over a person property across PersonsOnEventsMode × materialization.

    Master handles person-joined materialized properties correctly: ``ClickHousePrinter._get_table_name`` resolves the
    materialized-column registry key via ``to_printed_clickhouse`` (``RawPersonsTable`` → ``person``), so a person
    property read through the join still finds its materialized column. This test locks that, plus the §8.2 invariant
    that a non-nullable materialized column cannot represent "is set" (empty string collapses to NULL once materialized).
    """

    maxDiff = None

    def setUp(self) -> None:
        # Start from a clean materialized-column state: a prior suite test that left `email` materialized would make
        # the "not_materialized" variants read the mat column and fail. Defends the net against cross-test residue.
        super().setUp()
        cleanup_materialized_columns()

    @parameterized.expand(
        [
            ("materialized_joined", True, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
            ("materialized_on_events", True, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS),
            ("not_materialized_joined", False, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
            ("not_materialized_on_events", False, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS),
        ]
    )
    def test_person_property_is_not_set_behavior(
        self, _name: str, is_materialized: bool, poe_mode: PersonsOnEventsMode
    ) -> None:
        self.addCleanup(cleanup_materialized_columns)

        if is_materialized:
            materialize("events", "email", table_column="person_properties")
            materialize("person", "email")

        distinct_id_with_email = "test_with_email"
        distinct_id_with_empty = "test_with_empty_string"
        distinct_id_with_null = "test_with_null"
        distinct_id_without = "test_without"
        event_name = "is_not_set_test"

        # Four persons with different states of the email property.
        _create_person(
            distinct_ids=[distinct_id_with_email],
            team=self.team,
            properties={"email": "test@example.com"},
            immediate=True,
        )
        _create_person(
            distinct_ids=[distinct_id_with_empty],
            team=self.team,
            properties={"email": ""},
            immediate=True,
        )
        _create_person(
            distinct_ids=[distinct_id_with_null],
            team=self.team,
            properties={"email": None},
            immediate=True,
        )
        _create_person(
            distinct_ids=[distinct_id_without],
            team=self.team,
            properties={},
            immediate=True,
        )

        _create_event(team=self.team, event=event_name, distinct_id=distinct_id_with_email)
        _create_event(team=self.team, event=event_name, distinct_id=distinct_id_with_empty)
        _create_event(team=self.team, event=event_name, distinct_id=distinct_id_with_null)
        _create_event(team=self.team, event=event_name, distinct_id=distinct_id_without)
        flush_persons_and_events()

        is_not_set_expr = property_to_expr(
            {"type": "person", "key": "email", "operator": "is_not_set"},
            team=self.team,
            scope="event",
        )

        query_ast = ast.SelectQuery(
            select=[
                ast.Alias(alias="distinct_id", expr=ast.Field(chain=["distinct_id"])),
                ast.Alias(alias="email_value", expr=ast.Field(chain=["person", "properties", "email"])),
                ast.Alias(alias="is_not_set_result", expr=is_not_set_expr),
                # Historical is_not_set form (removed in PostHog/posthog#44346) — kept here to assert equivalence.
                ast.Alias(
                    alias="is_not_set_result_historical",
                    expr=ast.Or(
                        exprs=[
                            is_not_set_expr,
                            ast.Not(
                                expr=ast.Call(
                                    name="JSONHas",
                                    args=[ast.Field(chain=["person", "properties"]), ast.Constant(value="email")],
                                )
                            ),
                        ]
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=event_name),
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["distinct_id"]))],
        )

        result = execute_hogql_query(
            team=self.team,
            query=query_ast,
            modifiers=HogQLQueryModifiers(personsOnEventsMode=poe_mode),
        )
        assert result.clickhouse

        # Materializing collapses empty string to NULL (nullIf(nullIf(col, ''), 'null')) — a known, deliberate
        # inconsistency: a non-nullable materialized column cannot distinguish '' from missing (doc §8.2).
        expected_results = {
            (distinct_id_with_email, "test@example.com", 0, 0),
            (
                distinct_id_with_empty,
                None if is_materialized else "",
                1 if is_materialized else 0,
                1 if is_materialized else 0,
            ),
            (distinct_id_with_null, None, 1, 1),
            (distinct_id_without, None, 1, 1),
        }
        self.assertEqual(set(result.results), expected_results)

        # The materialized path must not touch the JSON blob — that is the performance regression the column prevents.
        sql_lower = result.clickhouse.lower()
        # JSONHas appears exactly once, in is_not_set_result_historical, and nowhere else.
        assert sql_lower.count("jsonhas") == 1
        if is_materialized:
            assert sql_lower.count("json") == 1
            assert sql_lower.count("has") == 1
            assert sql_lower.count("contains") == 0


class TestPhysicalScenarios(ClickhouseTestMixin, APIBaseTest):
    """Execution + skip-index gate for the ``PHYSICAL_SCENARIOS`` corpus (doc §9.4).

    For each scenario: materialize the named column(s), insert events that match and don't match, run the HogQL, assert
    the result rows, and — for the index-eligible cases — assert the expected minmax skip index is used. The
    ``mat_is_not_set`` scenario locks the §8.2 footgun at master behavior: is-not-set reads the scrubbed materialized
    column and over-matches empty-string / ``"null"``-string vs the truthful blob answer.
    """

    maxDiff = None

    def setUp(self) -> None:
        # Clean materialized-column state before each scenario so inbound residue from another suite test can't make a
        # property appear (un)materialized unexpectedly. Defends the net against cross-test pollution.
        super().setUp()
        cleanup_materialized_columns()

    # The match/no-match event set used by every scenario. ``test_prop = 'v'`` is true for exactly one row; the rest
    # exercise other-value / empty-string / "null"-string / absent-key / explicit-null states so is-set and equality
    # are both meaningfully tested.
    EVENTS: tuple[tuple[str, dict], ...] = (
        ("match", {"test_prop": "v"}),
        ("other", {"test_prop": "other"}),
        ("a_in", {"test_prop": "a"}),
        ("empty", {"test_prop": ""}),
        ("null_str", {"test_prop": "null"}),
        ("absent", {}),
        ("explicit_null", {"test_prop": None}),
    )

    def _setup_events(self) -> None:
        for distinct_id, properties in self.EVENTS:
            _create_event(team=self.team, distinct_id=distinct_id, event="phys_event", properties=properties)
        flush_persons_and_events()

    def _modifiers(self, scenario: PhysicalScenario) -> HogQLQueryModifiers | None:
        if scenario.property_groups_mode is None:
            return None
        return HogQLQueryModifiers(propertyGroupsMode=cast(PropertyGroupsMode, scenario.property_groups_mode))

    # Per-scenario expected distinct_ids (ORDER BY distinct_id). Kept here next to the corpus so a reader sees both the
    # declarative scenario and the concrete oracle the events above produce.
    EXPECTED_MATCHES: dict[str, list[tuple[str]]] = {
        # test_prop = 'v' → only the single matching row.
        "mat_equals_nonnullable": [("match",)],
        "mat_equals_nullable": [("match",)],
        # test_prop IN ('a','b') → only the 'a' row.
        "mat_in": [("a_in",)],
        # IS NULL (is-not-set) over a NON-NULLABLE materialized column. This is the §8.2 footgun, characterized at
        # MASTER behavior: master rewrites the predicate to read the materialized column with nullIf-scrubbing
        # (``isNull(nullIf(nullIf(mat_test_prop, ''), 'null'))``), so empty-string AND the literal string ``"null"``
        # both collapse to "not set" — alongside genuinely absent / explicitly-null rows. So master returns 4 rows,
        # NOT the 2 the JSON blob would (``absent`` + ``explicit_null``). The divergence from the blob result is the
        # bug §8.2 describes; this test locks the current behavior and makes the divergence explicit (see
        # ``_assert_is_not_set_matches_master_mat_column_behavior``). It is NOT the corpus's target form — the
        # rearchitecture will later make this decline onto the blob; when it does, this expectation flips to the blob
        # result and the divergence assertion is removed.
        "mat_is_not_set": [("absent",), ("empty",), ("explicit_null",), ("null_str",)],
    }

    @parameterized.expand([(scenario.name, scenario) for scenario in PHYSICAL_SCENARIOS])
    def test_physical_scenario(self, name: str, scenario: PhysicalScenario) -> None:
        self.addCleanup(cleanup_materialized_columns)

        # Materialize the column(s) the scenario needs, with a minmax index so index-usage is assertable.
        mat_columns = {}
        for table, prop, table_column, is_nullable in scenario.materialized:
            mat_columns[(table, prop, table_column)] = materialize(
                table,
                prop,
                table_column=table_column,
                create_minmax_index=True,
                is_nullable=is_nullable,
            )

        self._setup_events()

        # Run the scenario's HogQL, projecting distinct_id so we can assert exact match rows. The corpus SQL is a
        # ``count()`` shape; we wrap the same predicate to get the row identities (count is asserted via len()).
        select_sql = scenario.sql.replace("SELECT count()", "SELECT distinct_id", 1) + " ORDER BY distinct_id"
        result = execute_hogql_query(team=self.team, query=select_sql, modifiers=self._modifiers(scenario))
        assert result.clickhouse is not None

        expected = self.EXPECTED_MATCHES[name]
        self.assertEqual(result.results, expected, f"{name}: wrong match rows\nSQL: {result.clickhouse}")

        # count() must agree with the row identities (the corpus shape is count()).
        count_result = execute_hogql_query(team=self.team, query=scenario.sql, modifiers=self._modifiers(scenario))
        assert count_result.results is not None
        self.assertEqual(count_result.results[0][0], len(expected))

        if name == "mat_is_not_set":
            self._assert_is_not_set_matches_master_mat_column_behavior(scenario, result.clickhouse, expected)
        else:
            self._assert_index_used(scenario, mat_columns, result.clickhouse)

    def _assert_index_used(
        self,
        scenario: PhysicalScenario,
        mat_columns: dict[tuple[str, str, str], object],
        clickhouse_sql: str,
    ) -> None:
        # The events-table materialized column is what the predicate compares against; its minmax index is the one the
        # plan should use.
        for (table, _prop, _table_column), column in mat_columns.items():
            if table != "events":
                continue
            index_name = get_minmax_index_name(column.name)  # type: ignore[attr-defined]
            assert get_index_from_explain(clickhouse_sql, index_name), (
                f"{scenario.name}: expected skip index {index_name} to be used\nSQL: {clickhouse_sql}"
            )

    def _assert_is_not_set_matches_master_mat_column_behavior(
        self, scenario: PhysicalScenario, clickhouse_sql: str, mat_results: list[tuple[str]]
    ) -> None:
        # §8.2 footgun, characterized at MASTER behavior (the corpus ``description`` states the *target*, which differs).
        #
        # Master DOES read the non-nullable materialized column for is-not-set, with nullIf-scrubbing. Because a
        # non-nullable mat column stores '' for both empty-string and missing — and the DEFAULT/JSONExtractRaw form
        # also yields the literal ``"null"`` for a JSON null — the scrub
        # ``isNull(nullIf(nullIf(mat_test_prop, ''), 'null'))`` treats empty-string AND ``"null"`` as not-set. That is
        # the silent data divergence §8.2 warns about: it returns *more* rows than the truthful blob key-existence does.
        (table, prop, table_column, _is_nullable) = scenario.materialized[0]
        mat_name = self._materialized_column_name(table, prop, table_column)
        sql_lower = clickhouse_sql.lower()

        # Lock the current physical form: the mat column is read and scrubbed; no JSONHas/JSONExtract on the blob.
        assert mat_name.lower() in sql_lower, (
            f"{scenario.name}: MASTER reads the materialized column {mat_name} for is-not-set\nSQL: {clickhouse_sql}"
        )
        assert "json" not in sql_lower, (
            f"{scenario.name}: MASTER does NOT touch the JSON blob here (it reads the scrubbed mat column)"
            f"\nSQL: {clickhouse_sql}"
        )

        # Make the §8.2 divergence explicit and machine-checked against the truthful blob answer. The materialized
        # column exists on the shared ``sharded_events`` schema for *all* teams once created, so we can't re-query the
        # blob form in this test; ``BLOB_TRUTH`` is the documented unmaterialized result for the same predicate (only
        # genuinely absent / explicitly-null keys), verified directly by the unmaterialized corpus path. The point of
        # §8.2: the materialized path returns strictly more rows, over-matching exactly the empty-string and
        # ``"null"``-string rows the non-nullable mat column cannot distinguish from missing.
        blob_truth = {("absent",), ("explicit_null",)}
        assert blob_truth.issubset(set(mat_results)), "mat is-not-set should be a superset of the blob truth"
        assert set(mat_results) - blob_truth == {("empty",), ("null_str",)}, (
            'the §8.2 over-match is exactly the empty-string and "null"-string rows the mat column cannot distinguish'
        )

    def _materialized_column_name(self, table: str, prop: str, table_column: str) -> str:
        from ee.clickhouse.materialized_columns.columns import get_materialized_columns  # noqa: PLC0415

        column = get_materialized_columns(table).get((prop, table_column))
        assert column is not None, f"expected materialized column for {table}.{prop} ({table_column})"
        return column.name
